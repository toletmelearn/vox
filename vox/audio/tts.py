"""Piper TTS wrapper: speak(text). Voice models download to
state_dir/cache/models/piper on first use (spec Section 15.8: models
download on first run, never bundled) — redirected off the home directory so
a constrained system drive isn't filled; see DECISIONS.md. Piper's
downloader uses plain urlopen(), not huggingface_hub, so no HF_HOME redirect
is needed here — download_dir is passed explicitly instead."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from piper import PiperVoice
from piper.download_voices import download_voice

from vox.config import get_settings
from vox.security.confirm import get_kill_switch

logger = logging.getLogger("vox.audio.tts")

_POLL_INTERVAL_S = 0.05

_voice: PiperVoice | None = None


def _voice_dir() -> Path:
    state_dir = Path(get_settings().paths.state_dir).expanduser()
    voice_dir = state_dir / "cache" / "models" / "piper"
    voice_dir.mkdir(parents=True, exist_ok=True)
    return voice_dir


def _get_voice() -> PiperVoice:
    global _voice
    if _voice is None:
        settings = get_settings().tts
        voice_dir = _voice_dir()
        model_path = voice_dir / f"{settings.voice}.onnx"
        if not model_path.exists():
            logger.info("Downloading Piper voice %r to %s", settings.voice, voice_dir)
            download_voice(settings.voice, voice_dir)
        _voice = PiperVoice.load(str(model_path), download_dir=str(voice_dir))
    return _voice


def speak(text: str) -> None:
    """Synthesize and play text aloud. Never raises — a TTS failure must not
    take down a command that otherwise succeeded (invariant 9: degrade,
    never brick)."""
    settings = get_settings().tts
    if not settings.enabled or not text.strip():
        return
    try:
        voice = _get_voice()
        chunks = list(voice.synthesize(text))
        if not chunks:
            return
        audio = np.concatenate([c.audio_float_array for c in chunks])
        kill_switch = get_kill_switch()
        sd.play(audio, samplerate=chunks[0].sample_rate)
        stream = sd.get_stream()
        # Polled rather than sd.wait() so the kill switch (spec Section 8.7:
        # "stops TTS") can interrupt playback instead of blocking until it
        # finishes naturally.
        while stream is not None and stream.active:
            if kill_switch.is_set():
                sd.stop()
                break
            time.sleep(_POLL_INTERVAL_S)
    except Exception:
        logger.warning("speak failed for %r", text, exc_info=True)
