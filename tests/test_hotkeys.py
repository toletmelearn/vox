"""hotkeys.py tests: TapHotkeyListener and AbortHotkeyListener are exercised
by injecting synthetic press/release events, never by holding a real key or
starting a real global listener (same approach as test_capture.py's
HotkeyCapture tests). on_trigger runs on its own thread, so tests poll
briefly rather than asserting immediately after release."""
from __future__ import annotations

import time

from pynput import keyboard

from vox.ui.hotkeys import AbortHotkeyListener, TapHotkeyListener


class _StubListener:
    """See test_capture.py's _StubListener: stands in for a real pynput
    Listener's .canonical() without needing a live keyboard hook backend."""

    def canonical(self, key: keyboard.KeyCode) -> keyboard.KeyCode:
        return keyboard.KeyCode.from_char("k")


def _wait_for(fired: list[int]) -> None:
    for _ in range(50):
        if fired:
            return
        time.sleep(0.01)


def test_tap_hotkey_listener_fires_once_on_tap():
    fired: list[int] = []
    listener = TapHotkeyListener("ctrl+alt+space", on_trigger=lambda: fired.append(1))

    listener._on_press(keyboard.Key.ctrl_l)
    listener._on_press(keyboard.Key.alt_l)
    listener._on_press(keyboard.Key.space)
    assert not fired  # armed, not yet triggered

    listener._on_release(keyboard.Key.space)
    _wait_for(fired)
    assert fired == [1]


def test_tap_hotkey_listener_ignores_none_key_events():
    listener = TapHotkeyListener("ctrl+alt+space", on_trigger=lambda: None)
    listener._on_press(None)  # must not raise
    listener._on_release(None)


def test_tap_hotkey_listener_recognises_letter_chord_despite_modifier_skewed_char():
    """Regression test for the real bug: ctrl+alt+k (and this project's
    actual ctrl+shift+k text hotkey) never opened the command bar because
    the real pynput event for the letter key under held modifiers doesn't
    equal KeyCode.from_char('k') from parse_chord."""
    fired: list[int] = []
    listener = TapHotkeyListener("ctrl+alt+k", on_trigger=lambda: fired.append(1))
    listener._listener = _StubListener()  # type: ignore[assignment]

    listener._on_press(keyboard.Key.ctrl_l)
    listener._on_press(keyboard.Key.alt_l)
    # The real hook delivers a bare-vk KeyCode here, not KeyCode.from_char("k").
    listener._on_press(keyboard.KeyCode(vk=75))
    assert listener._armed

    listener._on_release(keyboard.KeyCode(vk=75))
    _wait_for(fired)
    assert fired == [1]


def test_abort_hotkey_listener_fires_on_esc():
    fired: list[int] = []
    listener = AbortHotkeyListener(on_trigger=lambda: fired.append(1))
    listener._on_press(keyboard.Key.esc)
    _wait_for(fired)
    assert fired == [1]


def test_abort_hotkey_listener_ignores_other_keys():
    fired: list[int] = []
    listener = AbortHotkeyListener(on_trigger=lambda: fired.append(1))
    listener._on_press(keyboard.Key.space)
    listener._on_press(None)
    assert not fired
