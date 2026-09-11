"""Global hotkeys for the two UI-triggering actions that aren't push-to-talk
recording: a tap opens the command bar (spec Section 6D), Esc anywhere
triggers the kill switch (spec Section 8.7). Built on the same
ChordTracker/parse_chord primitives as audio/capture.py's push-to-talk
listener, without touching the microphone."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from pynput import keyboard

from vox.audio.capture import ChordTracker, parse_chord

logger = logging.getLogger("vox.ui.hotkeys")

_Key = keyboard.Key | keyboard.KeyCode


class TapHotkeyListener:
    """Fires on_trigger() once when the configured chord is pressed then
    released (a tap, not a hold) - used for the text hotkey opening the
    command bar. on_trigger runs on its own thread, same rationale as
    HotkeyCapture: pynput's hook callback must return near-instantly, and
    opening a Tkinter window is not instant."""

    def __init__(self, chord: str, on_trigger: Callable[[], None]) -> None:
        self._tracker = ChordTracker(parse_chord(chord))
        self._armed = False
        self._on_trigger = on_trigger
        self._listener: keyboard.Listener | None = None

    def _on_press(self, key: _Key | None) -> None:
        if key is None:
            return
        self._tracker.press(key)
        if self._tracker.is_held():
            self._armed = True

    def _on_release(self, key: _Key | None) -> None:
        if key is None:
            return
        was_armed = self._armed and self._tracker.is_chord_key(key)
        self._tracker.release(key)
        if was_armed:
            self._armed = False
            threading.Thread(target=self._on_trigger, daemon=True).start()

    def start(self) -> None:
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


class AbortHotkeyListener:
    """Esc anywhere triggers the kill switch. Separate from the tap/hold
    listeners since Esc is not rebindable (config.hotkeys.abort) and has no
    chord/hold semantics to track - a bare press is enough."""

    def __init__(self, on_trigger: Callable[[], None]) -> None:
        self._on_trigger = on_trigger
        self._listener: keyboard.Listener | None = None

    def _on_press(self, key: _Key | None) -> None:
        if key == keyboard.Key.esc:
            threading.Thread(target=self._on_trigger, daemon=True).start()

    def start(self) -> None:
        self._listener = keyboard.Listener(on_press=self._on_press)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
