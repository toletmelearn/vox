"""Audit log tests: rows are written before execution and updated after,
never deleted (spec Section 8.6)."""
from __future__ import annotations

import sqlite3


def test_write_pending_then_update_status(audit_log):
    row_id = audit_log.write_pending(
        transcript="make a folder called Test",
        tool="create_folder",
        args={"name": "Test", "parent": "desktop"},
        risk="safe",
        tier="text",
    )
    row = audit_log._conn.execute(
        "SELECT status, tool, risk FROM events WHERE id = ?", (row_id,)
    ).fetchone()
    assert row == ("pending", "create_folder", "safe")

    audit_log.update_status(row_id, status="executed", duration_ms=12)
    row = audit_log._conn.execute(
        "SELECT status, duration_ms FROM events WHERE id = ?", (row_id,)
    ).fetchone()
    assert row == ("executed", 12)


def test_audit_log_has_no_delete_api(audit_log):
    assert not hasattr(audit_log, "delete")
    assert not hasattr(audit_log, "delete_row")
