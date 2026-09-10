"""apps.py tests: config.apps is the only source of truth (spec Section 6,
tools/apps.py). No PATH search, no os.system — the adapter's launch() is
mocked, never a real process spawn."""
from __future__ import annotations

from vox.tools.apps import open_app


def test_open_app_unknown_name_fails_without_launching(jail_settings, mocker):
    mock_adapter = mocker.MagicMock()
    mocker.patch("vox.tools.apps.get_adapter", return_value=mock_adapter)

    result = open_app(app="some_random_app_not_in_config")

    assert not result.ok
    mock_adapter.launch.assert_not_called()


def test_open_app_known_name_launches_configured_exe(jail_settings, mocker):
    mock_adapter = mocker.MagicMock()
    mock_adapter.launch.return_value = True
    mocker.patch("vox.tools.apps.get_adapter", return_value=mock_adapter)

    result = open_app(app="Notepad")  # case-insensitive

    assert result.ok
    mock_adapter.launch.assert_called_once_with("notepad.exe")


def test_open_app_launch_failure_is_graceful(jail_settings, mocker):
    mock_adapter = mocker.MagicMock()
    mock_adapter.launch.return_value = False
    mocker.patch("vox.tools.apps.get_adapter", return_value=mock_adapter)

    result = open_app(app="chrome")
    assert not result.ok
