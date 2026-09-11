"""settings.py tests: validation, conflict detection, chord recording, and
the apply/rollback orchestration are all plain Python with injected fakes -
no real Tkinter window or OS hotkey registration (spec Section 13)."""
from __future__ import annotations

from pynput import keyboard

from vox.config import Settings
from vox.ui.settings import (
    ChordRecorder,
    apply_hotkey_change,
    chords_conflict,
    validate_hotkey_chord,
)


def test_validate_hotkey_chord_requires_a_modifier():
    ok, message = validate_hotkey_chord("k")
    assert not ok
    assert "modifier" in message.lower()


def test_validate_hotkey_chord_rejects_reserved_combos():
    for chord in ("ctrl+alt+del", "win+l", "ctrl+shift+esc", "alt+tab", "win+tab"):
        ok, message = validate_hotkey_chord(chord)
        assert not ok, chord
        assert "reserved" in message.lower()


def test_validate_hotkey_chord_warns_but_accepts_common_shortcuts():
    ok, message = validate_hotkey_chord("ctrl+c")
    assert ok
    assert message  # non-empty warning


def test_validate_hotkey_chord_accepts_a_clean_combo():
    ok, message = validate_hotkey_chord("ctrl+shift+space")
    assert ok
    assert message == ""


def test_validate_hotkey_chord_rejects_empty_input():
    ok, message = validate_hotkey_chord("")
    assert not ok


def test_chords_conflict_is_order_and_case_insensitive():
    assert chords_conflict("Ctrl+Alt+Space", "ctrl+alt+space")
    assert chords_conflict("alt+ctrl+k", "ctrl+alt+k")
    assert not chords_conflict("ctrl+alt+k", "ctrl+alt+space")


def test_chord_recorder_finalizes_only_after_all_keys_released():
    recorder = ChordRecorder()
    recorder.press(keyboard.Key.ctrl_l)
    assert recorder.result is None
    recorder.press(keyboard.Key.alt_l)
    recorder.press(keyboard.KeyCode.from_char("k"))
    assert recorder.result is None

    recorder.release(keyboard.KeyCode.from_char("k"))
    assert recorder.result is None  # ctrl/alt still held
    recorder.release(keyboard.Key.alt_l)
    recorder.release(keyboard.Key.ctrl_l)
    assert recorder.result == "ctrl+alt+k"


def test_chord_recorder_orders_modifiers_canonically_regardless_of_press_order():
    recorder = ChordRecorder()
    recorder.press(keyboard.Key.shift_l)
    recorder.press(keyboard.Key.ctrl_l)
    recorder.press(keyboard.KeyCode.from_char("j"))
    recorder.release(keyboard.KeyCode.from_char("j"))
    recorder.release(keyboard.Key.ctrl_l)
    recorder.release(keyboard.Key.shift_l)
    assert recorder.result == "ctrl+shift+j"


def _settings() -> Settings:
    settings = Settings()
    settings.hotkeys.voice = "ctrl+alt+space"
    settings.hotkeys.text = "ctrl+alt+k"
    return settings


def test_apply_hotkey_change_rejects_when_it_matches_the_other_hotkey():
    settings = _settings()
    ok, message = apply_hotkey_change(
        "voice", "ctrl+alt+k", settings, lambda c: True, lambda c: True, save=lambda s: None
    )
    assert not ok
    assert "different" in message.lower()
    assert settings.hotkeys.voice == "ctrl+alt+space"  # unchanged


def test_apply_hotkey_change_rejects_reserved_without_touching_os_or_settings():
    settings = _settings()
    verify_calls = []
    ok, message = apply_hotkey_change(
        "voice",
        "win+l",
        settings,
        lambda c: verify_calls.append(c) or True,
        lambda c: True,
        save=lambda s: None,
    )
    assert not ok
    assert not verify_calls  # never even reached the OS-availability check
    assert settings.hotkeys.voice == "ctrl+alt+space"


def test_apply_hotkey_change_rolls_back_when_another_app_holds_the_chord():
    settings = _settings()
    swap_calls: list[str] = []

    def swap(chord: str) -> bool:
        swap_calls.append(chord)
        return True

    ok, message = apply_hotkey_change(
        "voice", "ctrl+alt+n", settings, lambda c: False, swap, save=lambda s: None
    )
    assert not ok
    assert "already claimed" in message.lower()
    assert not swap_calls  # swap_listener is only called once availability is confirmed
    assert settings.hotkeys.voice == "ctrl+alt+space"


def test_apply_hotkey_change_rolls_back_when_registration_actually_fails():
    settings = _settings()
    swap_calls: list[str] = []

    def swap(chord: str) -> bool:
        swap_calls.append(chord)
        return chord != "ctrl+alt+n"  # the new chord fails to register

    ok, message = apply_hotkey_change(
        "voice", "ctrl+alt+n", settings, lambda c: True, swap, save=lambda s: None
    )
    assert not ok
    assert "rolled back" in message.lower()
    assert swap_calls == ["ctrl+alt+n", "ctrl+alt+space"]  # tried new, then restored old
    assert settings.hotkeys.voice == "ctrl+alt+space"


def test_apply_hotkey_change_succeeds_and_persists():
    settings = _settings()
    saved: list[Settings] = []

    ok, message = apply_hotkey_change(
        "text", "ctrl+alt+j", settings, lambda c: True, lambda c: True, save=saved.append
    )
    assert ok
    assert settings.hotkeys.text == "ctrl+alt+j"
    assert saved == [settings]
