"""tray.py tests: the pure, display-independent icon-image generator, plus
TrayApp.run()'s mainloop-crash retry logic with pystray.Icon fully mocked -
TrayApp itself must never open a real system tray icon or native message
loop in a test (spec Section 13)."""
from __future__ import annotations

from vox.config import Settings
from vox.ui.tray import _MAX_MAINLOOP_RESTARTS, TrayApp, make_icon_image


def test_make_icon_image_returns_correct_size():
    image = make_icon_image("idle")
    assert image.size == (64, 64)


def test_make_icon_image_states_are_visually_distinct():
    colors = {state: make_icon_image(state).getpixel((32, 32)) for state in (
        "idle", "listening", "thinking", "error"
    )}
    assert len(set(colors.values())) == 4  # every state gets its own color


def test_make_icon_image_unknown_state_falls_back_to_idle():
    assert make_icon_image("bogus").getpixel((32, 32)) == make_icon_image("idle").getpixel((32, 32))


def _make_tray_app(mocker):
    """pystray.Icon is fully mocked - construction, .run(), everything -
    so TrayApp never touches a real window or message loop."""
    mock_icon_cls = mocker.patch("vox.ui.tray.pystray.Icon")
    tray = TrayApp(Settings())
    return tray, mock_icon_cls


def test_run_returns_on_a_real_quit(mocker):
    """A menu-triggered Quit calls _quit() (setting _quit_requested) before
    Icon.run() returns - run() must return immediately, no restart."""
    tray, mock_icon_cls = _make_tray_app(mocker)
    tray._icon.run.side_effect = lambda setup=None: tray._quit()

    tray.run()

    tray._icon.run.assert_called_once()
    mock_icon_cls.assert_called_once()  # no replacement icon was created


def test_run_restarts_the_icon_after_a_mainloop_crash_then_recovers(mocker):
    """pystray's own _mainloop() swallows a GetMessage failure internally
    and returns normally (spec: real, live finding) - run() must not treat
    that silent return as a Quit. It should recreate the icon and keep
    going; a subsequent real Quit still ends the loop."""
    tray, mock_icon_cls = _make_tray_app(mocker)
    crashed_icon = tray._icon
    crashed_icon.run.side_effect = lambda setup=None: None  # crash: returns, no quit

    replacement_icon = mocker.MagicMock()
    replacement_icon.run.side_effect = lambda setup=None: tray._quit()
    mock_icon_cls.side_effect = [replacement_icon]  # first call already happened in __init__

    tray.run()

    crashed_icon.run.assert_called_once()
    replacement_icon.run.assert_called_once()
    assert tray._icon is replacement_icon
    assert mock_icon_cls.call_count == 2  # __init__'s own icon, plus one replacement


def test_run_swallows_an_exception_from_icon_run_and_retries(mocker):
    """A failure pystray doesn't catch internally (e.g. before _mainloop()
    even starts) must not propagate out of run() either - same invariant 9
    reasoning as the silent-return case."""
    tray, mock_icon_cls = _make_tray_app(mocker)
    tray._icon.run.side_effect = RuntimeError("boom")

    replacement_icon = mocker.MagicMock()
    replacement_icon.run.side_effect = lambda setup=None: tray._quit()
    mock_icon_cls.side_effect = [replacement_icon]

    tray.run()  # must not raise

    assert tray._icon is replacement_icon


def test_run_gives_up_after_max_restarts_and_falls_back_to_headless_wait(mocker):
    """Exhausting the retry budget must not crash the process (invariant 9)
    - it degrades to a headless wait, and Ctrl+C there still cleanly quits."""
    tray, mock_icon_cls = _make_tray_app(mocker)

    def _always_crashes(setup=None):
        return None  # every icon's run() "crashes" silently, never quits

    tray._icon.run.side_effect = _always_crashes
    replacements = [mocker.MagicMock() for _ in range(_MAX_MAINLOOP_RESTARTS)]
    for icon in replacements:
        icon.run.side_effect = _always_crashes
    mock_icon_cls.side_effect = replacements

    mock_wait = mocker.patch("vox.ui.tray.threading.Event")
    mock_wait.return_value.wait.side_effect = KeyboardInterrupt

    tray.run()  # must not raise, must not hang

    total_run_calls = 1 + sum(icon.run.call_count for icon in replacements)
    assert total_run_calls == _MAX_MAINLOOP_RESTARTS + 1
    assert tray._quit_requested is True  # Ctrl+C in the fallback wait quits cleanly
