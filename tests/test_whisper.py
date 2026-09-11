"""stt/whisper.py tests: faster_whisper.WhisperModel is mocked throughout —
no test may download a model or require one running (spec Section 13)."""
from __future__ import annotations

import numpy as np

import vox.stt.whisper as whisper_module


def _fake_segment(text: str, avg_logprob: float):
    class _Segment:
        pass

    seg = _Segment()
    seg.text = text
    seg.avg_logprob = avg_logprob
    return seg


def test_transcribe_returns_text_and_confidence(mocker, jail_settings):
    mock_model = mocker.MagicMock()
    mock_info = mocker.MagicMock(language="en")
    mock_model.transcribe.return_value = (
        [_fake_segment("hello world", -0.2)],
        mock_info,
    )
    mocker.patch.object(whisper_module, "_get_model", return_value=mock_model)

    pcm = np.zeros(16000 * 2, dtype=np.float32)
    transcript = whisper_module.transcribe(pcm)

    assert transcript.text == "hello world"
    assert transcript.language == "en"
    assert 0.0 <= transcript.confidence <= 1.0
    assert transcript.confidence == pytest_approx(0.8)
    assert transcript.duration_s == 2.0


def pytest_approx(value, tol=1e-6):
    class _Approx:
        def __eq__(self, other):
            return abs(other - value) < tol

    return _Approx()


def test_transcribe_no_segments_is_low_confidence(mocker, jail_settings):
    mock_model = mocker.MagicMock()
    mock_info = mocker.MagicMock(language=None)
    mock_model.transcribe.return_value = ([], mock_info)
    mocker.patch.object(whisper_module, "_get_model", return_value=mock_model)

    pcm = np.zeros(16000, dtype=np.float32)
    transcript = whisper_module.transcribe(pcm)

    assert transcript.text == ""
    assert transcript.confidence == 0.0
    assert transcript.language == "unknown"


def test_logprob_to_confidence_clamped():
    assert whisper_module._logprob_to_confidence(0.0) == 1.0
    assert whisper_module._logprob_to_confidence(-1.0) == 0.0
    assert whisper_module._logprob_to_confidence(-5.0) == 0.0
    assert whisper_module._logprob_to_confidence(1.0) == 1.0  # clamped, never > 1
