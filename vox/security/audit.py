"""Append-only SQLite audit log. Rows are written before execution with
status 'pending', then updated after. Application code never deletes rows —
see spec Section 8.6 and CLAUDE.md invariant 5. This is a separate store from
memory (Section 6C); forget_activity (Phase 6) must never touch this file."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

Status = Literal["pending", "executed", "rejected", "failed", "cancelled"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  transcript TEXT,
  stt_confidence REAL,
  tier TEXT,
  tool TEXT,
  args_json TEXT,
  risk TEXT,
  confirmed INTEGER,
  status TEXT NOT NULL,
  error TEXT,
  duration_ms INTEGER
);
"""


class AuditLog:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.execute(_SCHEMA)

    def write_pending(
        self,
        *,
        transcript: str,
        tool: str | None,
        args: dict[str, Any] | None,
        risk: str | None,
        tier: str,
        stt_confidence: float | None = None,
        confirmed: bool = False,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO events
               (ts, transcript, stt_confidence, tier, tool, args_json, risk,
                confirmed, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                datetime.now(timezone.utc).isoformat(),
                transcript,
                stt_confidence,
                tier,
                tool,
                json.dumps(args or {}),
                risk,
                int(confirmed),
            ),
        )
        row_id = cur.lastrowid
        assert row_id is not None
        return row_id

    def update_status(
        self,
        row_id: int,
        *,
        status: Status,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self._conn.execute(
            "UPDATE events SET status = ?, error = ?, duration_ms = ? WHERE id = ?",
            (status, error, duration_ms, row_id),
        )

    def close(self) -> None:
        self._conn.close()


_audit_log: AuditLog | None = None


def get_audit_log() -> AuditLog:
    global _audit_log
    if _audit_log is None:
        from vox.config import get_settings

        state_dir = Path(get_settings().paths.state_dir).expanduser()
        _audit_log = AuditLog(state_dir / "audit.db")
    return _audit_log


def set_audit_log(log: AuditLog) -> None:
    """Test hook."""
    global _audit_log
    _audit_log = log


def reset_audit_log() -> None:
    """Test teardown hook: forget the cached audit log (does not delete its
    database file)."""
    global _audit_log
    _audit_log = None
