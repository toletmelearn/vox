"""The 4-step resolution ladder (spec Section 6A). `get_adapter` is mocked
throughout in both resolve.py and detect.py — no test opens a real window,
touches the real registry, or launches a real process."""
from __future__ import annotations

from vox.platform.base import WindowInfo
from vox.resolver.resolve import resolve_channel, resolve_target
from vox.resolver.targets import Target

_APP_TARGET = Target(
    key="whatsapp",
    display="WhatsApp",
    aliases=[],
    deep_link="whatsapp://",
    web_url="https://web.whatsapp.com",
    web_search_url=None,
    window_title_match=["WhatsApp"],
    windows_app_ids=["WhatsApp"],
    process_names=["WhatsApp.exe"],
    prefer="app",
)

_WEB_TARGET = Target(
    key="youtube",
    display="YouTube",
    aliases=[],
    deep_link=None,
    web_url="https://www.youtube.com",
    web_search_url=None,
    window_title_match=["YouTube"],
    windows_app_ids=[],
    process_names=[],
    prefer="web",
)


def _mock_adapter(mocker, *, capabilities, **overrides):
    adapter = mocker.MagicMock()
    adapter.capabilities.return_value = capabilities
    for name, value in overrides.items():
        getattr(adapter, name).return_value = value
    return adapter


def test_step1_focuses_already_open_window_and_opens_nothing_new(jail_settings, mocker):
    """Acceptance: 'go to YouTube' with a tab already open focuses that
    window and opens no new tab."""
    adapter = _mock_adapter(
        mocker,
        capabilities={"list_windows", "focus_window", "launch", "open_default_browser"},
        list_windows=[WindowInfo(handle=42, title="YouTube - Google Chrome")],
        focus_window=True,
    )
    mocker.patch("vox.resolver.resolve.get_adapter", return_value=adapter)
    mocker.patch("vox.resolver.detect.get_adapter", return_value=adapter)

    resolution = resolve_target(_WEB_TARGET, jail_settings)

    assert resolution.ok
    assert resolution.method == "focused_existing"
    adapter.focus_window.assert_called_once_with(42)
    adapter.open_default_browser.assert_not_called()
    adapter.launch.assert_not_called()


def test_step2_launches_installed_app_via_deep_link(jail_settings, mocker, memory_store):
    adapter = _mock_adapter(
        mocker,
        capabilities={"list_windows", "focus_window", "launch", "running_processes", "find_installed_app"},
        list_windows=[],
        running_processes=set(),
        find_installed_app="C:/Program Files/WhatsApp/WhatsApp.exe",
        launch=True,
    )
    mocker.patch("vox.resolver.resolve.get_adapter", return_value=adapter)
    mocker.patch("vox.resolver.detect.get_adapter", return_value=adapter)

    resolution = resolve_target(_APP_TARGET, jail_settings)

    assert resolution.ok
    assert resolution.method == "launched_app"
    adapter.launch.assert_called_once_with("whatsapp://")  # deep link preferred over the exe path


def test_uninstalled_app_falls_back_to_web(jail_settings, mocker, memory_store):
    """Acceptance: with WhatsApp uninstalled (empty process_names and
    windows_app_ids), it opens web.whatsapp.com instead."""
    uninstalled = Target(
        key="whatsapp",
        display="WhatsApp",
        aliases=[],
        deep_link="whatsapp://",
        web_url="https://web.whatsapp.com",
        web_search_url=None,
        window_title_match=["WhatsApp"],
        windows_app_ids=[],
        process_names=[],
        prefer="app",
    )
    adapter = _mock_adapter(
        mocker,
        capabilities={"list_windows", "focus_window", "launch", "running_processes", "open_default_browser"},
        list_windows=[],
        running_processes=set(),
        open_default_browser=True,
    )
    mocker.patch("vox.resolver.resolve.get_adapter", return_value=adapter)
    mocker.patch("vox.resolver.detect.get_adapter", return_value=adapter)

    resolution = resolve_target(uninstalled, jail_settings)

    assert resolution.ok
    assert resolution.method == "default_browser"
    adapter.open_default_browser.assert_called_once_with("https://web.whatsapp.com")
    adapter.launch.assert_not_called()


def test_install_detection_is_cached_no_repeat_registry_access(jail_settings, mocker, memory_store):
    """Acceptance: 'Install detection is cached; a second open_target call
    within the TTL performs no registry access (assert with a spy).'"""
    adapter = _mock_adapter(
        mocker,
        capabilities={"list_windows", "focus_window", "launch", "running_processes", "find_installed_app"},
        list_windows=[],
        running_processes=set(),
        find_installed_app="C:/Program Files/WhatsApp/WhatsApp.exe",
        launch=True,
    )
    mocker.patch("vox.resolver.resolve.get_adapter", return_value=adapter)
    mocker.patch("vox.resolver.detect.get_adapter", return_value=adapter)

    first = resolve_target(_APP_TARGET, jail_settings)
    second = resolve_target(_APP_TARGET, jail_settings)

    assert first.ok and second.ok
    adapter.find_installed_app.assert_called_once()  # not called again within the TTL


def test_resolve_channel_skips_step1_and_opens_the_supplied_payload(jail_settings, mocker):
    """play_on_target/compose_whatsapp_message need a *specific* new URL,
    not a refocused generic tab — resolve_channel never even calls
    list_windows/focus_window."""
    adapter = _mock_adapter(
        mocker,
        capabilities={"list_windows", "focus_window", "launch", "open_default_browser"},
        open_default_browser=True,
    )
    mocker.patch("vox.resolver.resolve.get_adapter", return_value=adapter)
    mocker.patch("vox.resolver.detect.get_adapter", return_value=adapter)

    resolution = resolve_channel(
        _WEB_TARGET, jail_settings, deep_link=None, web_url="https://www.youtube.com/watch?v=abc123"
    )

    assert resolution.ok
    adapter.list_windows.assert_not_called()
    adapter.focus_window.assert_not_called()
    adapter.open_default_browser.assert_called_once_with("https://www.youtube.com/watch?v=abc123")


def test_nothing_reachable_never_silently_does_nothing(jail_settings, mocker):
    adapter = _mock_adapter(mocker, capabilities=set())
    mocker.patch("vox.resolver.resolve.get_adapter", return_value=adapter)
    mocker.patch("vox.resolver.detect.get_adapter", return_value=adapter)

    resolution = resolve_target(_WEB_TARGET, jail_settings)

    assert not resolution.ok
    assert resolution.reason is not None
