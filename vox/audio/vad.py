"""Silero VAD, ONNX only — no torch (spec Section 3, "VAD — use ONNX, not
torch"). The ~2.3 MB model is vendored directly at models/silero_vad.onnx
(MIT licensed, see models/SILERO_VAD_LICENSE.txt) rather than pulled in via
the `silero-vad` PyPI package, which hard-depends on torch+torchaudio in its
own install_requires regardless of any ONNX-backend flag — see DECISIONS.md.

Silero v5's streaming convention requires a CONTEXT_SAMPLES-sample lookback
from the tail of the previous chunk, prepended to each new chunk, so the
model actually receives FRAME_SAMPLES + CONTEXT_SAMPLES samples per call —
not just FRAME_SAMPLES. Missing this produced near-zero probabilities for
*any* audio regardless of content (confirmed on both synthetic TTS and real
recorded speech during live acceptance testing) — see DECISIONS.md for the
full investigation. This is not documented in the exported graph's shape
metadata (which just says [None, None]); it's a convention of how the model
was trained, so a shape check alone doesn't catch it.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import onnxruntime

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512  # new-audio samples consumed per call at 16kHz
CONTEXT_SAMPLES = 64  # lookback from the previous chunk, prepended to each call

_MODEL_PATH = Path(__file__).parent / "models" / "silero_vad.onnx"


class SileroVAD:
    def __init__(self, model_path: Path = _MODEL_PATH) -> None:
        self._session = onnxruntime.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT_SAMPLES, dtype=np.float32)

    def speech_probability(self, frame: np.ndarray) -> float:
        """frame: 1-D float32 PCM, exactly FRAME_SAMPLES long. Internally
        prepends the lookback context from the previous call."""
        model_input = np.concatenate([self._context, frame]).reshape(1, -1).astype(np.float32)
        sr = np.array(SAMPLE_RATE, dtype=np.int64)
        output, state_n = self._session.run(
            ["output", "stateN"], {"input": model_input, "state": self._state, "sr": sr}
        )
        self._state = state_n
        self._context = frame[-CONTEXT_SAMPLES:].astype(np.float32)
        return float(output[0][0])


def _frame_speech_flags(
    pcm: np.ndarray, vad: SileroVAD, threshold: float
) -> list[bool]:
    vad.reset()
    n_frames = len(pcm) // FRAME_SAMPLES
    flags = []
    for i in range(n_frames):
        frame = pcm[i * FRAME_SAMPLES : (i + 1) * FRAME_SAMPLES]
        flags.append(vad.speech_probability(frame) >= threshold)
    return flags


def trim_silence(
    pcm: np.ndarray, vad: SileroVAD | None = None, threshold: float = 0.5
) -> np.ndarray:
    """Trim leading/trailing silence from a full recorded clip. Returns an
    empty array if no frame ever crosses the threshold — a hotkey press with
    no speech must produce no routing attempt (spec Section 10, Phase 3
    acceptance)."""
    if len(pcm) < FRAME_SAMPLES:
        return np.array([], dtype=np.float32)

    owned_vad = vad or SileroVAD()
    flags = _frame_speech_flags(pcm, owned_vad, threshold)

    if not any(flags):
        return np.array([], dtype=np.float32)

    first = flags.index(True)
    last = len(flags) - 1 - flags[::-1].index(True)
    start = first * FRAME_SAMPLES
    end = min((last + 1) * FRAME_SAMPLES, len(pcm))
    return pcm[start:end]


def has_speech(pcm: np.ndarray, vad: SileroVAD | None = None, threshold: float = 0.5) -> bool:
    return len(trim_silence(pcm, vad=vad, threshold=threshold)) > 0
