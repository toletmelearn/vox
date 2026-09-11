"""The on-disk `~/.vox/` folder layout (spec Section 6C) and artifact
archiving. Split out of `memory/store.py` (SQLite only) to keep that module
under CLAUDE.md's 300-line guideline."""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from vox.platform import get_adapter
from vox.platform.base import UnsupportedCapability

if TYPE_CHECKING:
    from vox.config import Settings

logger = logging.getLogger("vox.memory.tree")


def ensure_state_tree(state_dir: Path) -> list[Path]:
    """Creates the full `~/.vox/` tree (spec Section 6C folder layout) and
    locks each directory down to the current user only. Returns the
    directories it created/verified, for the caller to log or test against."""
    dirs = [
        state_dir,
        state_dir / "memory",
        state_dir / "artifacts",
        state_dir / "cache" / "models",
        state_dir / "transcripts",
    ]
    adapter = get_adapter()
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        try:
            adapter.restrict_directory_to_current_user(d)
        except UnsupportedCapability:
            pass  # degrade, never brick (invariant 9) - just less private on this platform

    empty_defaults: dict[str, dict[str, object]] = {
        "memory/contacts.json": {},
        "memory/aliases.json": {},
        "memory/preferences.json": {},
    }
    for name, default in empty_defaults.items():
        path = state_dir / name
        if not path.exists():
            path.write_text(json.dumps(default), encoding="utf-8")

    return dirs


def append_transcript(state_dir: Path, text: str) -> None:
    """Raw transcript log, `transcripts/YYYY-MM.jsonl` (spec Section 6C).
    Callers must only invoke this when `config.memory.store_transcripts` is
    true - the whole point of that setting is that with it false, no spoken
    text is written to disk anywhere (Phase 6 acceptance criterion)."""
    transcripts_dir = state_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    path = transcripts_dir / f"{datetime.now().strftime('%Y-%m')}.jsonl"
    line = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "text": text})
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def prune_transcripts(state_dir: Path, retention_days: int, *, now: datetime | None = None) -> int:
    """Deletes whole `YYYY-MM.jsonl` files entirely outside the retention
    window. Coarser than the DB's exact-day pruning (memory/store.py's
    `prune_older_than`) since the file is sharded by month, not by day -
    see DECISIONS.md."""
    now = now or datetime.now()
    cutoff_month = (now - timedelta(days=retention_days)).strftime("%Y-%m")
    transcripts_dir = state_dir / "transcripts"
    if not transcripts_dir.exists():
        return 0
    removed = 0
    for f in transcripts_dir.glob("*.jsonl"):
        if f.stem < cutoff_month:
            f.unlink()
            removed += 1
    return removed


def archive_artifact(path: Path, state_dir: Path) -> None:
    """Hardlinks (falling back to a copy across volumes) the artifact into
    `<state_dir>/artifacts/YYYY-MM-DD/` (spec Section 6C). No OS-detection
    branching needed here - os.link()/shutil.copy2() are already portable."""
    dest_dir = state_dir / "artifacts" / datetime.now().strftime("%Y-%m-%d")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        return
    try:
        os.link(path, dest)
    except OSError:
        try:
            shutil.copy2(path, dest)
        except OSError:
            logger.warning("could not archive artifact %r", path, exc_info=True)


def run_startup_maintenance(settings: Settings) -> None:
    """Bootstrap-time work for the memory store (spec Section 6C): create
    the tree on first run, then prune old activity/transcripts and sweep
    for artifacts whose files have vanished. Runs once per process start,
    not on a real daily schedule - this desktop app has no separate
    scheduler process to run a recurring job in (see DECISIONS.md)."""
    from vox.memory.store import get_memory_store

    state_dir = Path(settings.paths.state_dir).expanduser()
    ensure_state_tree(state_dir)

    store = get_memory_store()
    retention_days = settings.memory.transcript_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    pruned = store.prune_older_than(cutoff)
    removed_files = prune_transcripts(state_dir, retention_days)
    swept = store.sweep_missing_artifacts()
    if pruned or swept or removed_files:
        logger.info(
            "Memory retention: pruned %d old activity rows, %d old transcript files, "
            "%d artifacts now missing.",
            pruned,
            removed_files,
            swept,
        )
