"""Settings window: hotkey rebinding from the UI, not only by hand-editing
YAML (spec Section 6E). The validation/apply/rollback logic is plain Python
(`validate_hotkey_chord`, `chords_conflict`, `ChordRecorder`,
`apply_hotkey_change`) so it's fully testable with fakes; `SettingsWindow` is
the thin Tkinter shell wiring it to the real adapter, the live tray
listeners, and config.yaml."""
from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from typing import Literal

from pynput import keyboard

from vox.config import Settings, save_settings

logger = logging.getLogger("vox.ui.settings")

_Key = keyboard.Key | keyboard.KeyCode

_MODIFIER_TOKENS = {"ctrl", "alt", "shift", "win", "cmd"}

_RESERVED_CHORDS: set[frozenset[str]] = {
    frozenset({"ctrl", "alt", "del"}),
    frozenset({"ctrl", "alt", "delete"}),
    frozenset({"win", "l"}),
    frozenset({"ctrl", "shift", "esc"}),
    frozenset({"ctrl", "shift", "escape"}),
    frozenset({"alt", "tab"}),
    frozenset({"win", "tab"}),
}

_WARN_CHORDS: set[frozenset[str]] = {
    frozenset({"ctrl", "c"}),
    frozenset({"ctrl", "v"}),
    frozenset({"ctrl", "s"}),
    frozenset({"ctrl", "z"}),
    frozenset({"alt", "f4"}),
}

_MODIFIER_KEY_TOKENS: dict[_Key, str] = {
    keyboard.Key.ctrl_l: "ctrl",
    keyboard.Key.ctrl_r: "ctrl",
    keyboard.Key.alt_l: "alt",
    keyboard.Key.alt_r: "alt",
    keyboard.Key.shift_l: "shift",
    keyboard.Key.shift_r: "shift",
    keyboard.Key.cmd_l: "win",
    keyboard.Key.cmd_r: "win",
}

_NAMED_KEY_TOKENS: dict[_Key, str] = {
    keyboard.Key.space: "space",
    keyboard.Key.esc: "esc",
    keyboard.Key.tab: "tab",
    keyboard.Key.enter: "enter",
}

_MODIFIER_ORDER = ["ctrl", "alt", "shift", "win"]


def _normalize_chord(chord: str) -> frozenset[str]:
    return frozenset(t.strip().lower() for t in chord.split("+") if t.strip())


def validate_hotkey_chord(chord: str) -> tuple[bool, str]:
    """Returns (accepted, message). accepted=False rejects outright with a
    reason; accepted=True with a non-empty message is a non-blocking warning
    (spec Section 6E's validation table)."""
    tokens = _normalize_chord(chord)
    if not tokens:
        return False, "Enter a key combination."
    if not (tokens & _MODIFIER_TOKENS):
        return False, "Must include at least one modifier (Ctrl/Alt/Shift/Win)."
    if tokens in _RESERVED_CHORDS:
        return False, f"{chord} is reserved by Windows and can't be used here."
    if tokens in _WARN_CHORDS:
        return True, f"{chord} is a common application shortcut - you may lose it elsewhere."
    return True, ""


def chords_conflict(a: str, b: str) -> bool:
    return _normalize_chord(a) == _normalize_chord(b)


def _chord_string(keys: set[_Key]) -> str:
    modifiers: set[str] = set()
    others: list[str] = []
    for key in keys:
        if key in _MODIFIER_KEY_TOKENS:
            modifiers.add(_MODIFIER_KEY_TOKENS[key])
        elif key in _NAMED_KEY_TOKENS:
            others.append(_NAMED_KEY_TOKENS[key])
        elif isinstance(key, keyboard.KeyCode) and key.char:
            others.append(key.char.lower())
    ordered_mods = [m for m in _MODIFIER_ORDER if m in modifiers]
    return "+".join(ordered_mods + others)


class ChordRecorder:
    """Records the next chord a user presses for the settings window's
    'Change' capture widget: press some keys, release them all, and the
    union of everything that was down at some point during that
    press-release cycle is the captured chord. A pure state machine, tested
    the same way audio/capture.py's ChordTracker is - by injecting synthetic
    press/release events, never a real held key."""

    def __init__(self) -> None:
        self._held: set[_Key] = set()
        self._peak: set[_Key] = set()
        self.result: str | None = None

    def press(self, key: _Key) -> None:
        self._held.add(key)
        self._peak.add(key)

    def release(self, key: _Key) -> None:
        self._held.discard(key)
        if not self._held and self._peak:
            self.result = _chord_string(self._peak)
            self._peak = set()


def apply_hotkey_change(
    kind: Literal["voice", "text"],
    new_chord: str,
    settings: Settings,
    verify_available: Callable[[str], bool],
    swap_listener: Callable[[str], bool],
    save: Callable[[Settings], None] = save_settings,
) -> tuple[bool, str]:
    """Validate, check OS availability, swap the live listener, and persist -
    or roll back to the previous chord and say why (spec Section 10 Phase 5
    acceptance: 'rebinding to a chord already held by another app rolls back
    and shows a visible message'). `swap_listener` actually unregisters the
    old chord and registers the new one on the running listener; it returns
    False if registration failed."""
    other = settings.hotkeys.text if kind == "voice" else settings.hotkeys.voice
    if chords_conflict(new_chord, other):
        return False, "Voice and text hotkeys must be different."

    accepted, message = validate_hotkey_chord(new_chord)
    if not accepted:
        return False, message

    if not verify_available(new_chord):
        return False, f"{new_chord} is already claimed by another application."

    old_chord = settings.hotkeys.voice if kind == "voice" else settings.hotkeys.text
    if not swap_listener(new_chord):
        swap_listener(old_chord)  # roll back to the previous working chord
        return False, f"Could not register {new_chord}; rolled back to {old_chord}."

    if kind == "voice":
        settings.hotkeys.voice = new_chord
    else:
        settings.hotkeys.text = new_chord
    save(settings)
    return True, message or f"{new_chord} is now active."


class SettingsWindow:
    """Tkinter settings window. One instance is built and shown per open,
    same lifecycle as CommandBar and the confirm dialog."""

    def __init__(
        self,
        settings: Settings,
        verify_available: Callable[[str], bool],
        swap_voice_listener: Callable[[str], bool],
        swap_text_listener: Callable[[str], bool],
    ) -> None:
        self._settings = settings
        self._verify_available = verify_available
        self._swap_voice_listener = swap_voice_listener
        self._swap_text_listener = swap_text_listener

    def _capture_chord(self, on_done: Callable[[str], None]) -> None:
        recorder = ChordRecorder()
        listener_holder: list[keyboard.Listener] = []

        def _on_press(key: _Key | None) -> None:
            if key is not None:
                recorder.press(key)

        def _on_release(key: _Key | None) -> None:
            if key is not None:
                recorder.release(key)
            if recorder.result is not None:
                listener_holder[0].stop()
                on_done(recorder.result)

        listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
        listener_holder.append(listener)
        listener.start()

    def _row(self, parent: tk.Misc, label: str, kind: Literal["voice", "text"]) -> None:
        chord = self._settings.hotkeys.voice if kind == "voice" else self._settings.hotkeys.text
        frame = tk.Frame(parent)
        frame.pack(fill="x", padx=12, pady=6)
        tk.Label(frame, text=label, width=10, anchor="w").pack(side="left")
        value = tk.StringVar(value=chord)
        tk.Label(frame, textvariable=value, width=20, anchor="w", font=("Consolas", 10)).pack(
            side="left"
        )
        status = tk.Label(frame, text="", fg="#b00000", anchor="w")

        def _on_captured(new_chord: str) -> None:
            swap = self._swap_voice_listener if kind == "voice" else self._swap_text_listener
            ok, message = apply_hotkey_change(
                kind, new_chord, self._settings, self._verify_available, swap
            )
            if ok:
                value.set(getattr(self._settings.hotkeys, kind))
            status.config(text=message, fg="#806000" if ok else "#b00000")
            status.pack(side="left", padx=8)

        def _on_change_clicked() -> None:
            status.config(text="Press a key combination...", fg="#444444")
            status.pack(side="left", padx=8)
            self._capture_chord(_on_captured)

        tk.Button(frame, text="Change", command=_on_change_clicked).pack(side="left", padx=8)

    def show(self) -> None:
        root = tk.Tk()
        root.title("vox settings")
        root.attributes("-topmost", True)
        root.resizable(False, False)

        tk.Label(root, text="Hotkeys", font=("Segoe UI", 11, "bold")).pack(
            padx=12, pady=(12, 4), anchor="w"
        )
        self._row(root, "Voice", "voice")
        self._row(root, "Text", "text")
        tk.Label(
            root, text="Esc (kill switch) is not rebindable.", fg="#888888", font=("Segoe UI", 9)
        ).pack(padx=12, pady=(0, 8), anchor="w")

        tk.Button(root, text="Close", command=root.destroy).pack(pady=(0, 12))
        root.mainloop()
