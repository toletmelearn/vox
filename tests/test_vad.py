"""VAD tests use the real vendored ONNX model (a local file, no network
call) — genuine correctness, not a mock. Silence must trim to empty (spec
Section 10, Phase 3: a hotkey press with no speech produces no routing
attempt). The torch-import assertion is required verbatim by spec Section 3
("VAD — use ONNX, not torch")."""
from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

from vox.audio.vad import FRAME_SAMPLES, SAMPLE_RATE, SileroVAD, has_speech, trim_silence

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_speech_16k.wav"


def _load_fixture(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def test_torch_is_never_imported_by_vad():
    assert "torch" not in sys.modules


def test_pure_silence_trims_to_empty():
    silence = np.zeros(SAMPLE_RATE * 2, dtype=np.float32)
    assert len(trim_silence(silence)) == 0
    assert not has_speech(silence)


def test_too_short_clip_returns_empty():
    tiny = np.zeros(FRAME_SAMPLES // 2, dtype=np.float32)
    assert len(trim_silence(tiny)) == 0


# Note: Silero correctly does NOT flag loud white noise as speech — it's
# discriminating real speech spectral structure, not just "is there
# signal." White noise isn't a usable synthetic stand-in for a positive
# "has speech" case; the fixture below (real synthesized speech, offline,
# no network) is used instead.


def test_real_speech_fixture_is_detected_and_trimmed():
    """Regression test for a real bug found during live acceptance testing:
    speech_probability() was missing Silero v5's required 64-sample
    lookback context prepended to each 512-sample chunk. Without it, EVERY
    input — synthetic TTS and real human speech alike — scored near zero
    regardless of content (max ~0.003 vs. the 0.5 threshold). With the fix,
    real recorded speech scored up to 0.999 (see DECISIONS.md for the full
    investigation). This fixture is Windows SAPI speech, generated offline
    — not the developer's voice, and no network call."""
    audio = _load_fixture(_FIXTURE_PATH)
    assert has_speech(audio)

    trimmed = trim_silence(audio)
    assert 0 < len(trimmed) < len(audio)  # leading/trailing silence removed, not all of it


def test_context_is_carried_between_calls():
    """The context buffer (last CONTEXT_SAMPLES of the previous frame) must
    actually change as frames are fed — a frozen/zero context is exactly
    the bug this test guards against."""
    vad = SileroVAD()
    initial_context = vad._context.copy()
    audio = _load_fixture(_FIXTURE_PATH)
    # Sample 5000 onward is well past the fixture's leading silence.
    vad.speech_probability(audio[5000 : 5000 + FRAME_SAMPLES])
    assert not np.array_equal(vad._context, initial_context)


def test_vad_reset_clears_recurrent_state():
    vad = SileroVAD()
    frame = np.zeros(FRAME_SAMPLES, dtype=np.float32)
    vad.speech_probability(frame)
    vad.reset()
    assert np.array_equal(vad._state, np.zeros((2, 1, 128), dtype=np.float32))
