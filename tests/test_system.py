"""system.py tests for set_volume, take_screenshot, lock_screen. The
platform adapter is mocked throughout — no real OS side effects."""
from __future__ import annotations

from pathlib import Path

from vox.platform.base import UnsupportedCapability
from vox.tools.system import lock_screen, set_volume, take_screenshot


def test_set_volume_clamps_and_delegates(jail_settings, mocker):
    mock_adapter = mocker.MagicMock()
    mock_adapter.set_volume.return_value = True
    mocker.patch("vox.tools.system.get_adapter", return_value=mock_adapter)

    result = set_volume(level=150)

    assert result.ok
    mock_adapter.set_volume.assert_called_once_with(100)


def test_set_volume_unsupported_is_graceful(jail_settings, mocker):
    mock_adapter = mocker.MagicMock()
    mock_adapter.set_volume.side_effect = UnsupportedCapability("no backend")
    mocker.patch("vox.tools.system.get_adapter", return_value=mock_adapter)

    result = set_volume(level=50)
    assert not result.ok


def test_take_screenshot_saves_via_adapter(jail_settings, mocker):
    mock_adapter = mocker.MagicMock()
    mock_adapter.screenshot.return_value = True
    mocker.patch("vox.tools.system.get_adapter", return_value=mock_adapter)

    result = take_screenshot()

    assert result.ok
    assert result.artifact_path is not None
    assert Path(result.artifact_path).parent == Path(jail_settings.paths.desktop).resolve()


def test_lock_screen_delegates_to_adapter(jail_settings, mocker):
    mock_adapter = mocker.MagicMock()
    mock_adapter.lock_screen.return_value = True
    mocker.patch("vox.tools.system.get_adapter", return_value=mock_adapter)

    result = lock_screen()
    assert result.ok
    mock_adapter.lock_screen.assert_called_once()
