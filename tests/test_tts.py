"""audio/tts.py tests: Piper's voice download and sounddevice playback are
mocked throughout — no test may download a voice model or touch real audio
hardware (spec Section 13)."""
from __future__ import annotations

import numpy as np
import pytest

import vox.audio.tts as tts_module


@pytest.fixture(autouse=True)
def _reset_voice_cache():
    tts_module._voice = None
    yield
    tts_module._voice = None


def _fake_chunk(samples: int, sample_rate: int = 22050):
    class _Chunk:
        pass

    chunk = _Chunk()
    chunk.audio_float_array = np.zeros(samples, dtype=np.float32)
    chunk.sample_rate = sample_rate
    return chunk


def test_speak_disabled_does_not_touch_voice_or_playback(mocker, jail_settings):
    jail_settings.tts.enabled = False
    get_voice_mock = mocker.patch.object(tts_module, "_get_voice")
    play_mock = mocker.patch("vox.audio.tts.sd.play")

    tts_module.speak("hello")

    get_voice_mock.assert_not_called()
    play_mock.assert_not_called()


def test_speak_empty_text_is_a_noop(mocker, jail_settings):
    get_voice_mock = mocker.patch.object(tts_module, "_get_voice")
    tts_module.speak("   ")
    get_voice_mock.assert_not_called()


def test_speak_synthesizes_and_plays(mocker, jail_settings):
    mock_voice = mocker.MagicMock()
    mock_voice.synthesize.return_value = [_fake_chunk(100), _fake_chunk(50)]
    mocker.patch.object(tts_module, "_get_voice", return_value=mock_voice)
    play_mock = mocker.patch("vox.audio.tts.sd.play")
    stop_mock = mocker.patch("vox.audio.tts.sd.stop")

    fake_stream = mocker.MagicMock()
    fake_stream.active = True

    def _finish_after_one_poll(_interval: float) -> None:
        fake_stream.active = False

    mocker.patch("vox.audio.tts.sd.get_stream", return_value=fake_stream)
    mocker.patch("vox.audio.tts.time.sleep", side_effect=_finish_after_one_poll)

    tts_module.speak("Created folder Test.")

    play_mock.assert_called_once()
    args, kwargs = play_mock.call_args
    assert len(args[0]) == 150
    stop_mock.assert_not_called()  # playback finished naturally, kill switch never fired


def test_speak_stops_playback_when_kill_switch_is_set(mocker, jail_settings):
    from vox.security.confirm import get_kill_switch

    mock_voice = mocker.MagicMock()
    mock_voice.synthesize.return_value = [_fake_chunk(100)]
    mocker.patch.object(tts_module, "_get_voice", return_value=mock_voice)
    mocker.patch("vox.audio.tts.sd.play")
    stop_mock = mocker.patch("vox.audio.tts.sd.stop")

    fake_stream = mocker.MagicMock()
    fake_stream.active = True
    mocker.patch("vox.audio.tts.sd.get_stream", return_value=fake_stream)
    mocker.patch("vox.audio.tts.time.sleep")

    kill_switch = get_kill_switch()
    kill_switch.trigger()
    try:
        tts_module.speak("this should be interrupted")
    finally:
        kill_switch.clear()

    stop_mock.assert_called_once()


def test_speak_never_raises_on_backend_failure(mocker, jail_settings):
    mocker.patch.object(tts_module, "_get_voice", side_effect=RuntimeError("no audio device"))
    tts_module.speak("this should not raise")  # must not propagate


def test_get_voice_downloads_only_when_missing(mocker, jail_settings, tmp_path):
    jail_settings.paths.state_dir = str(tmp_path / "state")
    download_mock = mocker.patch.object(tts_module, "download_voice")
    load_mock = mocker.patch.object(tts_module.PiperVoice, "load")

    tts_module._get_voice()

    download_mock.assert_called_once()
    load_mock.assert_called_once()
