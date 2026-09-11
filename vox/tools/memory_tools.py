"""Recall tools (spec Section 6C). `recall_activity` never calls a model -
see memory/recall.py's docstring. `forget_activity` only ever deletes from
the memory store; the audit log is a separate file it never opens."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from vox.memory.recall import summarize_activity
from vox.memory.store import get_memory_store
from vox.tools.registry import ToolResult, tool


@tool(
    name="recall_activity",
    risk="safe",
    description=(
        "Answer questions about what the agent did recently, e.g. "
        "'what did I do yesterday', 'what files did you make this week'."
    ),
)
def recall_activity(query: str, days: int = 7) -> ToolResult:
    store = get_memory_store()
    speech = summarize_activity(store, query, days)
    return ToolResult(ok=True, speech=speech)


@tool(
    name="find_recent_artifact",
    risk="safe",
    description="Find a file the agent created recently, by description or type.",
)
def find_recent_artifact(description: str = "", kind: str = "", days: int = 30) -> ToolResult:
    store = get_memory_store()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = store.artifacts_since(cutoff, kind=kind)

    if description:
        needle = description.lower()
        rows = [r for r in rows if needle in (r.title or "").lower() or needle in r.path.lower()]

    if not rows:
        return ToolResult(ok=True, speech="I couldn't find a matching file.")

    best = rows[0]
    name = best.title or Path(best.path).name
    return ToolResult(ok=True, speech=f"The most recent match is {name}.", artifact_path=best.path)


@tool(
    name="forget_activity",
    risk="destructive",
    description="Delete stored memory entries. Requires confirmation.",
)
def forget_activity(scope: Literal["last", "today", "all"]) -> ToolResult:
    store = get_memory_store()
    count = store.forget(scope)
    plural = "y" if count == 1 else "ies"
    return ToolResult(
        ok=True,
        speech=f"Cleared {count} memory entr{plural} for {scope}. This clears memory, not the security log.",
    )
