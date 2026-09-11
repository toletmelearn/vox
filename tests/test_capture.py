"""capture.py tests: ChordTracker and Recorder are pure state machines, so
they're tested without a real global keyboard listener or microphone.
HotkeyCapture is tested by injecting synthetic press/release events, never
by holding a real key (which no automated test can do)."""
from __future__ import annotations

import time

import numpy as np
import pytest
from pynput import keyboard

from vox.audio.capture import ChordTracker, HotkeyCapture, Recorder, parse_chord


def test_parse_chord_ctrl_alt_space():
    groups = parse_chord("ctrl+alt+space")
    assert len(groups) == 3
    assert keyboard.Key.ctrl_l in groups[0] and keyboard.Key.ctrl_r in groups[0]
    assert keyboard.Key.alt_l in groups[1] and keyboard.Key.alt_r in groups[1]
    assert groups[2] == frozenset({keyboard.Key.space})


def test_parse_chord_single_letter():
    groups = parse_chord("ctrl+alt+k")
    assert groups[2] == frozenset({keyboard.KeyCode.from_char("k")})


def test_parse_chord_rejects_unknown_token():
    with pytest.raises(ValueError):
        parse_chord("ctrl+banana")


def test_parse_chord_rejects_empty():
    with pytest.raises(ValueError):
        parse_chord("")


def test_chord_tracker_requires_every_group_held():
    tracker = ChordTracker(parse_chord("ctrl+alt+space"))
    assert not tracker.is_held()

    tracker.press(keyboard.Key.ctrl_l)
    assert not tracker.is_held()

    tracker.press(keyboard.Key.alt_r)  # either left or right alt counts
    assert not tracker.is_held()

    tracker.press(keyboard.Key.space)
    assert tracker.is_held()

    tracker.release(keyboard.Key.ctrl_l)
    assert not tracker.is_held()


def test_chord_tracker_is_chord_key():
    tracker = ChordTracker(parse_chord("ctrl+alt+space"))
    assert tracker.is_chord_key(keyboard.Key.ctrl_l)
    assert tracker.is_chord_key(keyboard.Key.alt_r)
    assert not tracker.is_chord_key(keyboard.Key.shift_l)


def test_recorder_start_stop_uses_mocked_stream(mocker):
    mock_stream_cls = mocker.patch("vox.audio.capture.sd.InputStream")
    mock_stream = mock_stream_cls.return_value

    recorder = Recorder(sample_rate=16000)
    recorder.start()
    mock_stream.start.assert_called_once()

    # Simulate the audio callback pushing two chunks before release.
    callback = mock_stream_cls.call_args.kwargs["callback"]
    callback(np.ones((4, 1), dtype=np.float32), 4, None, None)
    callback(np.zeros((3, 1), dtype=np.float32), 3, None, None)

    pcm = recorder.stop()
    assert len(pcm) == 7
    mock_stream.stop.assert_called_once()
    mock_stream.close.assert_called_once()


def test_recorder_stop_without_frames_returns_empty_array():
    recorder = Recorder()
    pcm = recorder.stop()
    assert len(pcm) == 0


def test_hotkey_capture_records_only_while_chord_fully_held(mocker):
    mocker.patch("vox.audio.capture.sd.InputStream")
    recorded: list[np.ndarray] = []

    capture = HotkeyCapture("ctrl+alt+space", on_recorded=recorded.append)

    # Not yet fully held -> no recording started.
    capture._on_press(keyboard.Key.ctrl_l)
    assert not capture._recording

    capture._on_press(keyboard.Key.alt_l)
    capture._on_press(keyboard.Key.space)
    assert capture._recording

    # Releasing an unrelated key must not stop recording.
    capture._on_release(keyboard.Key.shift_l)
    assert capture._recording

    # Releasing a chord key stops recording and fires the callback. The
    # callback runs on the worker thread now, not inline — .join() is the
    # deterministic sync point (queue.Queue's own mechanism), not a sleep.
    capture._on_release(keyboard.Key.ctrl_l)
    assert not capture._recording
    capture._work.join()
    assert len(recorded) == 1
    capture.stop()


def test_hotkey_capture_ignores_none_key_events(mocker):
    mocker.patch("vox.audio.capture.sd.InputStream")
    capture = HotkeyCapture("ctrl+alt+space", on_recorded=lambda pcm: None)
    capture._on_press(None)  # must not raise
    capture._on_release(None)
    capture.stop()


def test_hotkey_capture_release_returns_fast_even_if_on_recorded_is_slow(mocker):
    """The regression this fixes: on_recorded (VAD+Whisper+TTS in the real
    app) must never run on pynput's hook-callback thread, where Windows can
    silently drop/delay events for a slow hook. _on_release itself must
    return near-instantly regardless of how long on_recorded takes."""
    mocker.patch("vox.audio.capture.sd.InputStream")

    def slow_on_recorded(pcm: np.ndarray) -> None:
        time.sleep(0.3)

    capture = HotkeyCapture("ctrl+alt+space", on_recorded=slow_on_recorded)
    capture._on_press(keyboard.Key.ctrl_l)
    capture._on_press(keyboard.Key.alt_l)
    capture._on_press(keyboard.Key.space)

    t0 = time.monotonic()
    capture._on_release(keyboard.Key.ctrl_l)
    elapsed = time.monotonic() - t0

    assert elapsed < 0.05, f"_on_release blocked for {elapsed:.3f}s — work leaked onto the hook thread"
    capture._work.join()
    capture.stop()
