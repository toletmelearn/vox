"""open_target / play_on_target / rescan_apps tools (spec Section 6A). No
real window enumeration, registry access, network call, or yt-dlp search —
get_adapter and YoutubeDL are mocked throughout."""
from __future__ import annotations

from vox.resolver.targets import Target, set_target_catalogue
from vox.tools.targets import open_target, play_on_target, rescan_apps

_YOUTUBE = Target(
    key="youtube",
    display="YouTube",
    aliases=["you tube", "yt", "utube"],
    deep_link=None,
    web_url="https://www.youtube.com",
    web_search_url="https://www.youtube.com/results?search_query={q}",
    window_title_match=["YouTube"],
    windows_app_ids=[],
    process_names=[],
    prefer="web",
)
_SPOTIFY = Target(
    key="spotify",
    display="Spotify",
    aliases=[],
    deep_link="spotify:",
    web_url="https://open.spotify.com",
    web_search_url="https://open.spotify.com/search/{q}",
    window_title_match=["Spotify"],
    windows_app_ids=["Spotify"],
    process_names=["Spotify.exe"],
    prefer="app",
)
_CATALOGUE = {"youtube": _YOUTUBE, "spotify": _SPOTIFY}


def _patch_adapter(mocker, **overrides):
    adapter = mocker.MagicMock()
    adapter.capabilities.return_value = {
        "list_windows",
        "focus_window",
        "launch",
        "running_processes",
        "find_installed_app",
        "open_default_browser",
        "running_browsers",
    }
    for name, value in overrides.items():
        getattr(adapter, name).return_value = value
    mocker.patch("vox.resolver.resolve.get_adapter", return_value=adapter)
    mocker.patch("vox.resolver.detect.get_adapter", return_value=adapter)
    return adapter


def test_open_target_unknown_service_clarifies_and_opens_nothing(jail_settings, mocker):
    set_target_catalogue(_CATALOGUE)
    adapter = _patch_adapter(mocker)

    result = open_target(target="flipkart")

    assert not result.ok
    adapter.launch.assert_not_called()
    adapter.open_default_browser.assert_not_called()


def test_open_target_fuzzy_alias_resolves(jail_settings, mocker, memory_store):
    set_target_catalogue(_CATALOGUE)
    _patch_adapter(mocker, list_windows=[], running_processes=set(), find_installed_app=None, open_default_browser=True)

    result = open_target(target="you tube")

    assert result.ok
    assert "YouTube" in result.speech


def test_play_on_target_youtube_opens_watch_url_not_search_page(jail_settings, mocker, memory_store):
    """Acceptance: 'play munni badnaam hui on YouTube' opens a watch?v= URL,
    not a search results page."""
    set_target_catalogue(_CATALOGUE)
    adapter = _patch_adapter(
        mocker, list_windows=[], running_processes=set(), find_installed_app=None, open_default_browser=True
    )

    mock_ydl = mocker.MagicMock()
    mock_ydl.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.return_value = {"entries": [{"id": "dQw4w9WgXcQ"}]}
    mocker.patch("vox.tools.targets.YoutubeDL", return_value=mock_ydl)

    result = play_on_target(target="youtube", query="munni badnaam hui")

    assert result.ok
    adapter.open_default_browser.assert_called_once_with("https://www.youtube.com/watch?v=dQw4w9WgXcQ")


def test_play_on_target_youtube_no_results_fails_without_opening_search_page(jail_settings, mocker):
    set_target_catalogue(_CATALOGUE)
    adapter = _patch_adapter(mocker)
    mock_ydl = mocker.MagicMock()
    mock_ydl.__enter__.return_value = mock_ydl
    mock_ydl.extract_info.return_value = {"entries": []}
    mocker.patch("vox.tools.targets.YoutubeDL", return_value=mock_ydl)

    result = play_on_target(target="youtube", query="asdkjaskldjaslkdj")

    assert not result.ok
    adapter.open_default_browser.assert_not_called()


def test_play_on_target_spotify_uses_search_deep_link_when_installed(jail_settings, mocker, memory_store):
    set_target_catalogue(_CATALOGUE)
    adapter = _patch_adapter(
        mocker, list_windows=[], running_processes={"Spotify.exe"}, launch=True
    )

    result = play_on_target(target="spotify", query="lofi beats")

    assert result.ok
    adapter.launch.assert_called_once_with("spotify:search:lofi%20beats")


def test_rescan_apps_clears_cache(jail_settings, memory_store):
    memory_store.set_app_cache("spotify", installed=True, exe_path="spotify.exe")
    assert memory_store.get_app_cache("spotify") is not None

    result = rescan_apps()

    assert result.ok
    assert memory_store.get_app_cache("spotify") is None
