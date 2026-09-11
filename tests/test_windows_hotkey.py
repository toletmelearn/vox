"""Windows hotkey-registration probe tests (spec Section 6E: "verify it
took," not just assume registration succeeded). This is the real check that
caught ctrl+alt+space being intercepted by another application on the dev
machine — see DECISIONS.md. ctypes calls are mocked; never actually claims
a real system-wide hotkey in tests."""
from __future__ import annotations

import pytest

from vox.platform.windows import (
    WindowsAdapter,
    _MOD_ALT,
    _MOD_CONTROL,
    _MOD_SHIFT,
    _parse_win_chord,
)


def test_parse_win_chord_ctrl_alt_space():
    mods, vk = _parse_win_chord("ctrl+alt+space")
    assert mods == _MOD_CONTROL | _MOD_ALT
    assert vk == 0x20


def test_parse_win_chord_ctrl_shift_letter():
    mods, vk = _parse_win_chord("ctrl+shift+k")
    assert mods == _MOD_CONTROL | _MOD_SHIFT
    assert vk == ord("K")


def test_parse_win_chord_rejects_modifiers_only():
    with pytest.raises(ValueError):
        _parse_win_chord("ctrl+alt")


def test_parse_win_chord_rejects_unknown_token():
    with pytest.raises(ValueError):
        _parse_win_chord("ctrl+banana")


def test_verify_hotkey_available_true_when_register_succeeds(mocker):
    mock_user32 = mocker.MagicMock()
    mock_user32.RegisterHotKey.return_value = 1  # nonzero = success
    mocker.patch("vox.platform.windows.ctypes.windll.user32", mock_user32)

    adapter = WindowsAdapter()
    assert adapter.verify_hotkey_available("ctrl+shift+space") is True
    mock_user32.UnregisterHotKey.assert_called_once()


def test_verify_hotkey_available_false_when_already_claimed(mocker):
    mock_user32 = mocker.MagicMock()
    mock_user32.RegisterHotKey.return_value = 0  # zero = failure (already registered)
    mocker.patch("vox.platform.windows.ctypes.windll.user32", mock_user32)

    adapter = WindowsAdapter()
    assert adapter.verify_hotkey_available("ctrl+alt+space") is False
    mock_user32.UnregisterHotKey.assert_not_called()


def test_verify_hotkey_available_false_on_unparseable_chord(mocker):
    mock_user32 = mocker.MagicMock()
    mocker.patch("vox.platform.windows.ctypes.windll.user32", mock_user32)

    adapter = WindowsAdapter()
    assert adapter.verify_hotkey_available("ctrl+alt+shift") is False  # no non-modifier key
    mock_user32.RegisterHotKey.assert_not_called()
