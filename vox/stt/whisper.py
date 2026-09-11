"""faster-whisper wrapper: transcribe(pcm) -> Transcript (spec Section 4)."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

from vox.config import get_settings
from vox.router.base import Transcript

logger = logging.getLogger("vox.stt.whisper")


def _redirect_hf_cache() -> None:
    """faster-whisper downloads CTranslate2 model snapshots via
    huggingface_hub, which defaults its cache under the user's home
    directory. Redirect under state_dir so first-run model downloads don't
    fill a constrained system drive (see DECISIONS.md). Must run before
    faster_whisper/huggingface_hub is imported anywhere in the process."""
    if "HF_HOME" in os.environ:
        return  # caller/shell already set it — don't override
    state_dir = Path(get_settings().paths.state_dir).expanduser()
    os.environ["HF_HOME"] = str(state_dir / "cache" / "huggingface")


_redirect_hf_cache()

from faster_whisper import WhisperModel  # noqa: E402 - must follow the HF_HOME redirect

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        settings = get_settings().stt
        logger.info("Loading Whisper model %r (%s/%s)", settings.model, settings.device, settings.compute_type)
        cpu_threads = (os.cpu_count() or 4) if settings.device == "cpu" else 0
        _model = WhisperModel(
            settings.model,
            device=settings.device,
            compute_type=settings.compute_type,
            cpu_threads=cpu_threads,
        )
    return _model


def _logprob_to_confidence(avg_logprob: float) -> float:
    """avg_logprob is a log-probability (0 = certain, more negative = less
    certain). Heuristic linear map to 0..1, clamped; not from the spec,
    documented here and in DECISIONS.md."""
    return max(0.0, min(1.0, 1.0 + avg_logprob))


def transcribe(pcm: np.ndarray, sample_rate: int = 16000) -> Transcript:
    settings = get_settings().stt
    model = _get_model()

    segments, info = model.transcribe(pcm, language=settings.language, task="transcribe")
    segments = list(segments)

    text = " ".join(s.text.strip() for s in segments).strip()
    if segments:
        avg_logprob = sum(s.avg_logprob for s in segments) / len(segments)
    else:
        avg_logprob = -1.0  # no segments recognised -> treat as low confidence

    return Transcript(
        text=text,
        confidence=_logprob_to_confidence(avg_logprob),
        language=info.language or "unknown",
        duration_s=len(pcm) / sample_rate,
    )
