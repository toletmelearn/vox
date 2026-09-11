"""Deterministic activity summaries (spec Section 6C): 'recall_activity must
NOT call an LLM to answer... Query the DB, format the rows, speak a
summary.' Model calls here are slow and can hallucinate activity that never
happened, defeating the point of having a record."""
from __future__ import annotations

from datetime import datetime, timedelta

from vox.memory.store import ActivityRow, MemoryStore

_MAX_SPOKEN_EXAMPLES = 3


def _resolve_window(query: str, days: int, now: datetime) -> tuple[datetime, datetime, str]:
    lowered = query.lower()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "yesterday" in lowered:
        return today_start - timedelta(days=1), today_start, "yesterday"
    if "today" in lowered:
        return today_start, now, "today"
    if "week" in lowered:
        return now - timedelta(days=7), now, "this week"
    return now - timedelta(days=days), now, f"the last {days} days"


def _describe(row: ActivityRow) -> str:
    if row.tool:
        return row.tool.replace("_", " ")
    return "something unclear"


def summarize_activity(
    store: MemoryStore, query: str, days: int = 7, *, now: datetime | None = None
) -> str:
    now = now or datetime.now()
    start, end, label = _resolve_window(query, days, now)
    rows = store.activity_between(start, end)

    if not rows:
        return f"I didn't do anything {label}."

    count = len(rows)
    examples = ", ".join(_describe(r) for r in rows[-_MAX_SPOKEN_EXAMPLES:])
    plural = "s" if count != 1 else ""
    return f"{count} thing{plural} {label}, most recently: {examples}."
