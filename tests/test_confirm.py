"""security/confirm.py tests: the destructive-risk modal, the kill switch,
and the medium-risk undo window. The real Tkinter dialog is never opened in
a test (spec Section 13) - set_confirm_handler injects a fake."""
from __future__ import annotations

from pathlib import Path

import pytest

from vox.app import handle_text
from vox.security import confirm


@pytest.fixture(autouse=True)
def _reset_confirm_state():
    yield
    confirm.reset_confirm_handler()
    confirm.reset_undo_state()
    confirm.get_kill_switch().clear()


def test_confirm_destructive_uses_injected_handler():
    confirm.set_confirm_handler(lambda tool, args: True)
    assert confirm.confirm_destructive("move_to_trash", {"path": "C:/x"}) is True

    confirm.set_confirm_handler(lambda tool, args: False)
    assert confirm.confirm_destructive("move_to_trash", {"path": "C:/x"}) is False


def test_destructive_tool_cancelled_writes_cancelled_status_and_does_not_execute(
    jail_settings, audit_log, mocker
):
    target = Path(jail_settings.paths.desktop, "keep_me.txt")
    target.write_text("hello", encoding="utf-8")
    send2trash_mock = mocker.patch("vox.tools.files.send2trash.send2trash")

    confirm.set_confirm_handler(lambda tool, args: False)  # Cancel
    # move_to_trash takes an absolute path, which Tier 0 has no phrasing
    # for - call execute_tool_call directly instead of via handle_text.
    from vox.app import execute_tool_call
    from vox.router.base import ToolCall

    result = execute_tool_call(
        ToolCall(name="move_to_trash", args={"path": str(target)}), transcript="delete keep_me.txt"
    )

    assert not result.ok
    send2trash_mock.assert_not_called()
    assert target.exists()

    row = audit_log._conn.execute(
        "SELECT status, tool FROM events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row == ("cancelled", "move_to_trash")


def test_destructive_tool_confirmed_executes_and_writes_executed_status(
    jail_settings, audit_log, mocker
):
    target = Path(jail_settings.paths.desktop, "delete_me.txt")
    target.write_text("hello", encoding="utf-8")
    send2trash_mock = mocker.patch("vox.tools.files.send2trash.send2trash")

    confirm.set_confirm_handler(lambda tool, args: True)  # Confirm
    from vox.app import execute_tool_call
    from vox.router.base import ToolCall

    result = execute_tool_call(
        ToolCall(name="move_to_trash", args={"path": str(target)}), transcript="delete delete_me.txt"
    )

    assert result.ok
    send2trash_mock.assert_called_once_with(str(target))

    row = audit_log._conn.execute(
        "SELECT status, tool FROM events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row == ("executed", "move_to_trash")


def test_kill_switch_starts_clear_and_can_be_triggered():
    switch = confirm.get_kill_switch()
    assert not switch.is_set()
    switch.trigger()
    assert switch.is_set()
    switch.clear()
    assert not switch.is_set()


def test_route_and_execute_clears_kill_switch_at_start_of_each_command(jail_settings, audit_log):
    confirm.get_kill_switch().trigger()
    assert confirm.get_kill_switch().is_set()

    handle_text("what's the time")

    assert not confirm.get_kill_switch().is_set()


def test_arm_undo_and_get_pending_undo_round_trip():
    assert confirm.get_pending_undo() is None
    confirm.arm_undo("download_file", "C:/Downloads/x.zip", window_s=10)
    pending = confirm.get_pending_undo()
    assert pending is not None
    assert pending.tool == "download_file"
    assert pending.artifact_path == "C:/Downloads/x.zip"


def test_pending_undo_expires_after_its_window():
    confirm.arm_undo("open_app", "C:/Downloads/x.zip", window_s=0.0)
    assert confirm.get_pending_undo() is None  # already past its (zero-length) window


def test_perform_undo_sends_to_trash_and_clears_pending(mocker):
    send2trash_mock = mocker.patch("vox.security.confirm.send2trash.send2trash")
    confirm.arm_undo("download_file", "C:/Downloads/x.zip", window_s=10)

    assert confirm.perform_undo() is True
    send2trash_mock.assert_called_once_with("C:/Downloads/x.zip")
    assert confirm.get_pending_undo() is None
    assert confirm.perform_undo() is False  # nothing left to undo


def test_perform_undo_with_nothing_armed_returns_false():
    assert confirm.perform_undo() is False


def test_undo_listener_is_called_when_armed():
    seen = []
    confirm.set_undo_listener(seen.append)
    confirm.arm_undo("open_url", "C:/x", window_s=4)
    assert len(seen) == 1
    assert seen[0].tool == "open_url"


def test_medium_risk_tool_success_arms_undo_window(jail_settings, audit_log, mocker):
    mocker.patch("vox.tools.apps.get_adapter").return_value.launch.return_value = True
    jail_settings.apps["notepad"] = "notepad.exe"

    from vox.app import execute_tool_call
    from vox.router.base import ToolCall

    assert confirm.get_pending_undo() is None
    result = execute_tool_call(ToolCall(name="open_app", args={"app": "notepad"}), transcript="open notepad")
    assert result.ok
    # open_app has no artifact_path, so no undo window opens for it - only
    # medium tools that actually produce an artifact do (spec Section 8.4:
    # "file creation, download").
    assert confirm.get_pending_undo() is None


def test_download_file_success_arms_a_real_undo_window(jail_settings, audit_log, mocker):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield b"file contents"

    mocker.patch("vox.tools.web.requests.get", return_value=FakeResponse())

    from vox.app import execute_tool_call
    from vox.router.base import ToolCall

    result = execute_tool_call(
        ToolCall(name="download_file", args={"url": "https://example.com/report.pdf"}),
        transcript="download https://example.com/report.pdf",
    )

    assert result.ok
    pending = confirm.get_pending_undo()
    assert pending is not None
    assert pending.tool == "download_file"
    assert pending.artifact_path == result.artifact_path
    assert pending.window_s == jail_settings.security.undo_window_s
