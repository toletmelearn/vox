"""Append-only SQLite audit log. Rows are written before execution with
status 'pending', then updated after. Application code never deletes rows —
see spec Section 8.6 and CLAUDE.md invariant 5. This is a separate store from
memory (Section 6C); forget_activity (Phase 6) must never touch this file."""
from __future__ import annotations

import json
import sqlite3
import threading
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
    """`execute_tool_call` (app.py) calls `get_audit_log()` from whichever
    thread is running a command - the pystray setup thread for the text
    hotkey/command bar, and HotkeyCapture's dedicated worker thread (Phase 3)
    for voice - and a single `sqlite3.Connection` can only ever be used from
    the thread that created it. A module-level singleton connection meant
    the *first* caller's thread silently "claimed" it, and every other
    thread's later write crashed with sqlite3.ProgrammingError - confirmed
    live. Fixed with one real connection per thread (`threading.local`),
    each opened with WAL journaling and a busy timeout so the rare case of
    two threads writing at the same moment retries instead of raising
    "database is locked", rather than a single shared connection with
    `check_same_thread=False` papering over the same race."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._connect().execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    @property
    def _conn(self) -> sqlite3.Connection:
        """Thread-local connection, exposed as an attribute for tests that
        inspect the current thread's rows directly."""
        return self._connect()

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
        """Closes only the calling thread's connection. Other threads keep
        theirs open; they're daemon worker threads that die with the
        process, per this project's threading model."""
        conn: sqlite3.Connection | None = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


_audit_log: AuditLog | None = None
_audit_log_lock = threading.Lock()


def get_audit_log() -> AuditLog:
    global _audit_log
    if _audit_log is None:
        with _audit_log_lock:
            if _audit_log is None:  # re-check: another thread may have won the race
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
