"""memory/recall.py tests: summarize_activity must never call a model (spec
Section 6C) - there is no client passed in here at all, only the DB.

`now` is always passed as a UTC-aware datetime here, matching how activity
rows are actually stored (datetime.now(timezone.utc) in
memory/store.py::record_activity) - this keeps the tests independent of the
machine's local timezone, which a naive `now` would not be (naive
datetimes are astimezone()'d as *local* time by activity_between)."""
from __future__ import annotations

from datetime import datetime, timezone

from vox.memory.recall import summarize_activity


def _insert(memory_store, ts: str, tool: str) -> None:
    memory_store._conn.execute(
        "INSERT INTO activity (ts, session_id, transcript, tool, args_json, outcome, speech) "
        "VALUES (?, 's1', 'x', ?, '{}', 'ok', 'a')",
        (ts, tool),
    )


def test_summarize_activity_empty_window_says_nothing_happened(memory_store):
    now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    speech = summarize_activity(memory_store, "today", now=now)
    assert "didn't do anything" in speech
    assert "today" in speech


def test_summarize_activity_today_counts_only_todays_rows(memory_store):
    now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    _insert(memory_store, "2026-01-15T08:00:00+00:00", "create_folder")  # today
    _insert(memory_store, "2026-01-14T08:00:00+00:00", "get_time")  # yesterday, excluded

    speech = summarize_activity(memory_store, "today", now=now)

    assert "1 thing today" in speech
    assert "create folder" in speech


def test_summarize_activity_yesterday_excludes_today(memory_store):
    now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    _insert(memory_store, "2026-01-14T08:00:00+00:00", "get_time")  # yesterday
    _insert(memory_store, "2026-01-15T08:00:00+00:00", "take_screenshot")  # today, excluded

    speech = summarize_activity(memory_store, "yesterday", now=now)

    assert "1 thing yesterday" in speech
    assert "get time" in speech


def test_summarize_activity_this_week_uses_a_seven_day_window(memory_store):
    now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    _insert(memory_store, "2026-01-10T08:00:00+00:00", "get_time")  # within 7 days
    _insert(memory_store, "2025-12-01T08:00:00+00:00", "get_time")  # outside 7 days

    speech = summarize_activity(memory_store, "this week", now=now)

    assert "1 thing this week" in speech


def test_summarize_activity_falls_back_to_days_param(memory_store):
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    speech = summarize_activity(memory_store, "something unusual", days=3, now=now)
    assert "last 3 days" in speech
