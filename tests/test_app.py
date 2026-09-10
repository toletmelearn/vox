"""End-to-end text pipeline tests matching the Phase 1 acceptance criteria
verbatim (spec Section 10)."""
from __future__ import annotations

from pathlib import Path

from vox.app import handle_text


def _row_count(audit_log) -> int:
    return audit_log._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def test_make_folder_creates_it_and_writes_one_audit_row(jail_settings, audit_log):
    result = handle_text("make a folder called Test")
    assert result.ok
    assert Path(jail_settings.paths.desktop, "Test").is_dir()
    assert _row_count(audit_log) == 1

    row = audit_log._conn.execute("SELECT status, tool FROM events").fetchone()
    assert row == ("executed", "create_folder")


def test_make_folder_traversal_is_rejected_no_folder_no_execution(jail_settings, audit_log):
    result = handle_text("make a folder called ../../evil")
    assert not result.ok

    row = audit_log._conn.execute("SELECT status, tool FROM events").fetchone()
    assert row == ("rejected", "create_folder")

    # nowhere outside the jailed tmp_path tree should have anything created
    assert not (Path(jail_settings.paths.desktop).parent.parent / "evil").exists()


def test_unrecognised_text_returns_clarification_without_audit_row(jail_settings, audit_log):
    result = handle_text("book me a flight to Goa")
    assert not result.ok
    assert _row_count(audit_log) == 0
