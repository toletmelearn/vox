"""Memory store (spec Section 6C): SQLite at `<state_dir>/memory/memory.db`.
This is a *separate* store from the audit log (`security/audit.py`) -
editable and prunable, unlike the audit log's append-only guarantee.
`forget()` only ever touches this file. The on-disk `~/.vox/` folder tree
itself is `memory/tree.py`, not here."""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("vox.memory.store")

ForgetScope = Literal["last", "today", "all"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  session_id TEXT NOT NULL,
  transcript TEXT NOT NULL,
  tool TEXT,
  args_json TEXT,
  outcome TEXT,
  speech TEXT,
  artifact_id INTEGER
);

CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  path TEXT NOT NULL,
  kind TEXT,
  title TEXT,
  source_transcript TEXT,
  still_exists INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  started_at TEXT,
  ended_at TEXT,
  command_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app_cache (
  target TEXT PRIMARY KEY,
  installed INTEGER,
  exe_path TEXT,
  checked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_activity_ts ON activity(ts);
CREATE INDEX IF NOT EXISTS idx_artifacts_ts ON artifacts(ts);
"""

# Tool name -> artifact kind, for tools whose output extension doesn't
# already say it (a download can be any extension; a folder has none).
# Anything not listed here falls back to a suffix guess.
_ARTIFACT_KIND_BY_TOOL = {
    "create_folder": "folder",
    "create_text_file": "txt",
    "create_word_document": "docx",
    "create_pdf": "pdf",
    "convert_to_pdf": "pdf",
    "download_file": "download",
    "take_screenshot": "screenshot",
}


def artifact_kind(tool: str, path: str) -> str:
    if tool in _ARTIFACT_KIND_BY_TOOL:
        return _ARTIFACT_KIND_BY_TOOL[tool]
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix or "file"


@dataclass(frozen=True)
class ActivityRow:
    id: int
    ts: str
    transcript: str
    tool: str | None
    outcome: str | None
    speech: str | None


@dataclass(frozen=True)
class ArtifactRow:
    id: int
    ts: str
    path: str
    kind: str | None
    title: str | None
    still_exists: bool


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, isolation_level=None)
        self._conn.executescript(_SCHEMA)

    # -- activity ------------------------------------------------------
    def record_activity(
        self,
        *,
        session_id: str,
        transcript: str,
        tool: str | None,
        args: dict[str, Any] | None,
        outcome: str,
        speech: str,
        artifact_id: int | None = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO activity
               (ts, session_id, transcript, tool, args_json, outcome, speech, artifact_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                session_id,
                transcript,
                tool,
                json.dumps(args or {}),
                outcome,
                speech,
                artifact_id,
            ),
        )
        row_id = cur.lastrowid
        assert row_id is not None
        return row_id

    def activity_between(self, start: datetime, end: datetime) -> list[ActivityRow]:
        rows = self._conn.execute(
            """SELECT id, ts, transcript, tool, outcome, speech FROM activity
               WHERE ts >= ? AND ts < ? ORDER BY ts ASC""",
            (start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()),
        ).fetchall()
        return [ActivityRow(*row) for row in rows]

    # -- artifacts -------------------------------------------------------
    def record_artifact(self, *, path: str, kind: str, title: str, source_transcript: str) -> int:
        cur = self._conn.execute(
            """INSERT INTO artifacts (ts, path, kind, title, source_transcript, still_exists)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (datetime.now(timezone.utc).isoformat(), path, kind, title, source_transcript),
        )
        row_id = cur.lastrowid
        assert row_id is not None
        return row_id

    def recent_artifacts(self, *, kind: str = "", limit: int = 30) -> list[ArtifactRow]:
        if kind:
            rows = self._conn.execute(
                """SELECT id, ts, path, kind, title, still_exists FROM artifacts
                   WHERE kind = ? ORDER BY ts DESC LIMIT ?""",
                (kind, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, ts, path, kind, title, still_exists FROM artifacts ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [ArtifactRow(r[0], r[1], r[2], r[3], r[4], bool(r[5])) for r in rows]

    def artifacts_since(self, cutoff: datetime, *, kind: str = "") -> list[ArtifactRow]:
        if kind:
            rows = self._conn.execute(
                """SELECT id, ts, path, kind, title, still_exists FROM artifacts
                   WHERE ts >= ? AND kind = ? ORDER BY ts DESC""",
                (cutoff.astimezone(timezone.utc).isoformat(), kind),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, ts, path, kind, title, still_exists FROM artifacts WHERE ts >= ? ORDER BY ts DESC",
                (cutoff.astimezone(timezone.utc).isoformat(),),
            ).fetchall()
        return [ArtifactRow(r[0], r[1], r[2], r[3], r[4], bool(r[5])) for r in rows]

    def sweep_missing_artifacts(self) -> int:
        """Daily background check (spec Section 6C): mark artifacts whose
        path has vanished. Never deletes the row - knowing a file *was*
        created and is now gone is useful. Run once per process start, since
        this desktop app has no separate scheduler process (see
        DECISIONS.md)."""
        rows = self._conn.execute(
            "SELECT id, path FROM artifacts WHERE still_exists = 1"
        ).fetchall()
        updated = 0
        for artifact_id, path in rows:
            if not Path(path).exists():
                self._conn.execute(
                    "UPDATE artifacts SET still_exists = 0 WHERE id = ?", (artifact_id,)
                )
                updated += 1
        return updated

    # -- sessions --------------------------------------------------------
    def start_session(self, session_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR IGNORE INTO sessions (id, started_at, ended_at, command_count) VALUES (?, ?, ?, 0)",
            (session_id, now, now),
        )

    def touch_session(self, session_id: str) -> None:
        self._conn.execute(
            """UPDATE sessions SET ended_at = ?, command_count = command_count + 1
               WHERE id = ?""",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )

    # -- retention / forgetting ------------------------------------------
    def prune_older_than(self, cutoff: datetime) -> int:
        cur = self._conn.execute("DELETE FROM activity WHERE ts < ?", (cutoff.astimezone(timezone.utc).isoformat(),))
        return cur.rowcount

    def forget(self, scope: ForgetScope) -> int:
        """Deletes from *this* store only - never touches audit.db (a
        separate file entirely; see the module docstring and spec Section
        6C: 'It never touches audit.db')."""
        if scope == "all":
            cur = self._conn.execute("DELETE FROM activity")
            self._conn.execute("DELETE FROM artifacts")
            self._conn.execute("DELETE FROM sessions")
            return cur.rowcount
        if scope == "today":
            start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            cur = self._conn.execute(
                "DELETE FROM activity WHERE ts >= ?", (start.isoformat(),)
            )
            return cur.rowcount
        # "last": the single most recent activity row.
        row = self._conn.execute("SELECT id FROM activity ORDER BY ts DESC LIMIT 1").fetchone()
        if row is None:
            return 0
        self._conn.execute("DELETE FROM activity WHERE id = ?", (row[0],))
        return 1

    def close(self) -> None:
        self._conn.close()


_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        from vox.config import get_settings

        state_dir = Path(get_settings().paths.state_dir).expanduser()
        _store = MemoryStore(state_dir / "memory" / "memory.db")
    return _store


def set_memory_store(store: MemoryStore) -> None:
    """Test hook."""
    global _store
    _store = store


def reset_memory_store() -> None:
    global _store
    _store = None
