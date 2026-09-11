"""web.py tests. No test may open a real network connection (spec Section
13) — requests and yt_dlp.YoutubeDL are mocked throughout."""
from __future__ import annotations

from pathlib import Path

import pytest

from vox.security.confirm import get_kill_switch
from vox.tools.web import UrlValidationError, _validate_url, download_file, play_youtube


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/x",
        "http://192.168.1.1/x",
        "javascript:alert(1)",
        "data:text/plain;base64,aGk=",
        "http://localhost/x",
    ],
)
def test_validate_url_rejects_unsafe_urls(url):
    with pytest.raises(UrlValidationError):
        _validate_url(url, blocked_hosts=[])


def test_validate_url_accepts_public_https():
    assert _validate_url("https://example.com/a", blocked_hosts=[]) == "example.com"


def test_validate_url_respects_blocked_hosts_config():
    with pytest.raises(UrlValidationError):
        _validate_url("https://blocked.example/x", blocked_hosts=["blocked.example"])


def test_play_youtube_opens_watch_url(jail_settings, mocker):
    mock_ydl_instance = mocker.MagicMock()
    mock_ydl_instance.__enter__.return_value = mock_ydl_instance
    mock_ydl_instance.extract_info.return_value = {"entries": [{"id": "dQw4w9WgXcQ"}]}
    mocker.patch("vox.tools.web.YoutubeDL", return_value=mock_ydl_instance)

    mock_adapter = mocker.MagicMock()
    mock_adapter.open_default_browser.return_value = True
    mocker.patch("vox.tools.web.get_adapter", return_value=mock_adapter)

    result = play_youtube(query="some song")

    assert result.ok
    mock_adapter.open_default_browser.assert_called_once_with(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )


def test_play_youtube_no_results_fails_gracefully(jail_settings, mocker):
    mock_ydl_instance = mocker.MagicMock()
    mock_ydl_instance.__enter__.return_value = mock_ydl_instance
    mock_ydl_instance.extract_info.return_value = {"entries": []}
    mocker.patch("vox.tools.web.YoutubeDL", return_value=mock_ydl_instance)

    result = play_youtube(query="nonsense query")
    assert not result.ok


def test_download_file_rejects_unsafe_url_without_network(jail_settings, mocker):
    request_mock = mocker.patch("vox.tools.web.requests.get")
    result = download_file(url="http://127.0.0.1/evil.exe")
    assert not result.ok
    request_mock.assert_not_called()


def test_download_file_streams_and_saves(jail_settings, mocker):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"hello "
            yield b"world"

    mocker.patch("vox.tools.web.requests.get", return_value=FakeResponse())

    result = download_file(url="https://example.com/greeting.txt")
    assert result.ok
    dest = Path(jail_settings.paths.downloads, "greeting.txt")
    assert dest.read_bytes() == b"hello world"


def test_download_file_enforces_max_size(jail_settings, mocker):
    settings = jail_settings
    settings.security.max_download_mb = 0  # any content exceeds 0 MB

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"x" * 1024

    mocker.patch("vox.tools.web.requests.get", return_value=FakeResponse())

    result = download_file(url="https://example.com/big.bin")
    assert not result.ok
    assert not Path(jail_settings.paths.downloads, "big.bin").exists()


def test_download_file_aborts_on_kill_switch_and_cleans_up_temp_file(jail_settings, mocker):
    """Spec Section 10 Phase 5 acceptance: 'Esc during a large download
    aborts it and cleans up the temp file.' The kill switch is checked
    inside the chunk loop (spec Section 8.7); this simulates Esc firing
    partway through a download."""
    kill_switch = get_kill_switch()

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"first chunk"
            kill_switch.trigger()  # simulate Esc firing mid-download
            yield b"second chunk, never written"

    mocker.patch("vox.tools.web.requests.get", return_value=FakeResponse())

    tmp_paths_created: list[Path] = []
    import tempfile as tempfile_module

    real_mkstemp = tempfile_module.mkstemp

    def _tracking_mkstemp(*args, **kwargs):
        fd, path_str = real_mkstemp(*args, **kwargs)
        tmp_paths_created.append(Path(path_str))
        return fd, path_str

    mocker.patch("vox.tools.web.tempfile.mkstemp", side_effect=_tracking_mkstemp)

    try:
        result = download_file(url="https://example.com/big.bin")
    finally:
        kill_switch.clear()

    assert not result.ok
    assert not Path(jail_settings.paths.downloads, "big.bin").exists()
    assert len(tmp_paths_created) == 1
    assert not tmp_paths_created[0].exists()  # temp file cleaned up, not left behind
