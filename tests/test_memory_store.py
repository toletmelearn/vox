"""memory/store.py tests: the SQLite side of the memory store, kept
completely separate from security/audit.py's append-only audit.db (spec
Section 6C)."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from vox.memory.store import MemoryStore, artifact_kind


def test_artifact_kind_uses_tool_table_first(memory_store):
    assert artifact_kind("create_folder", "C:/Desktop/Test") == "folder"
    assert artifact_kind("download_file", "C:/Downloads/report.pdf") == "download"


def test_artifact_kind_falls_back_to_suffix():
    assert artifact_kind("some_future_tool", "C:/x/report.pdf") == "pdf"
    assert artifact_kind("some_future_tool", "C:/x/noext") == "file"


def test_record_artifact_from_a_different_thread_than_the_store_was_created_on(tmp_path):
    """Regression test for a real live bug, identical to security/audit.py's
    AuditLog fix: MemoryStore opened one sqlite3.Connection at construction
    time, usable only from that thread. record_execution() - called from
    HotkeyCapture's dedicated voice worker thread - calling record_artifact()
    on a store constructed on a different thread (the pystray setup thread)
    crashed with sqlite3.ProgrammingError. Confirmed live: a real voice
    command ("make a word file called memory test") created the file
    correctly, but its memory row silently never landed because the
    exception was swallowed by app.py's _record_execution_safely. Reproduces
    the exact shape: construct on this thread, write from a second real
    thread."""
    store = MemoryStore(tmp_path / "memory.db")
    errors: list[BaseException] = []

    def _write_from_other_thread() -> None:
        try:
            store.record_artifact(
                path="C:/Desktop/memory test.docx",
                kind="docx",
                title="memory test.docx",
                source_transcript="make a word file called memory test",
            )
        except BaseException as exc:  # noqa: BLE001 - captured for the assertion below, not swallowed
            errors.append(exc)

    thread = threading.Thread(target=_write_from_other_thread)
    thread.start()
    thread.join()

    assert errors == [], f"record_artifact raised on a different thread: {errors!r}"
    rows = store.recent_artifacts()
    assert len(rows) == 1
    assert rows[0].title == "memory test.docx"

    store.close()


def test_record_and_query_activity(memory_store: MemoryStore):
    memory_store.record_activity(
        session_id="s1", transcript="make a folder called Test", tool="create_folder",
        args={"name": "Test"}, outcome="ok", speech="Created folder Test.",
    )
    now = datetime.now(timezone.utc)
    rows = memory_store.activity_between(now - timedelta(minutes=5), now + timedelta(minutes=5))
    assert len(rows) == 1
    assert rows[0].tool == "create_folder"
    assert rows[0].outcome == "ok"


def test_activity_between_excludes_rows_outside_the_window(memory_store: MemoryStore):
    memory_store.record_activity(
        session_id="s1", transcript="x", tool="get_time", args={}, outcome="ok", speech="It's noon.",
    )
    now = datetime.now(timezone.utc)
    rows = memory_store.activity_between(now + timedelta(hours=1), now + timedelta(hours=2))
    assert rows == []


def test_record_artifact_and_recent_artifacts(memory_store: MemoryStore):
    memory_store.record_artifact(
        path="C:/Documents/Notes.docx", kind="docx", title="Notes.docx", source_transcript="make a word file"
    )
    rows = memory_store.recent_artifacts()
    assert len(rows) == 1
    assert rows[0].path == "C:/Documents/Notes.docx"
    assert rows[0].still_exists is True


def test_recent_artifacts_filters_by_kind(memory_store: MemoryStore):
    memory_store.record_artifact(path="C:/a.docx", kind="docx", title="a.docx", source_transcript="x")
    memory_store.record_artifact(path="C:/b.pdf", kind="pdf", title="b.pdf", source_transcript="x")
    assert [r.path for r in memory_store.recent_artifacts(kind="pdf")] == ["C:/b.pdf"]


def test_sweep_missing_artifacts_marks_vanished_files(memory_store: MemoryStore, tmp_path):
    real_file = tmp_path / "real.txt"
    real_file.write_text("hi", encoding="utf-8")
    memory_store.record_artifact(path=str(real_file), kind="txt", title="real.txt", source_transcript="x")
    memory_store.record_artifact(
        path=str(tmp_path / "gone.txt"), kind="txt", title="gone.txt", source_transcript="x"
    )

    updated = memory_store.sweep_missing_artifacts()

    assert updated == 1
    rows = {r.path: r.still_exists for r in memory_store.recent_artifacts()}
    assert rows[str(real_file)] is True
    assert rows[str(tmp_path / "gone.txt")] is False


def test_sweep_missing_artifacts_never_deletes_the_row(memory_store: MemoryStore, tmp_path):
    memory_store.record_artifact(
        path=str(tmp_path / "gone.txt"), kind="txt", title="gone.txt", source_transcript="x"
    )
    memory_store.sweep_missing_artifacts()
    assert len(memory_store.recent_artifacts()) == 1  # row still present, just still_exists=0


def test_forget_today_deletes_only_todays_activity(memory_store: MemoryStore):
    old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    memory_store._conn.execute(
        "INSERT INTO activity (ts, session_id, transcript, tool, args_json, outcome, speech) "
        "VALUES (?, 's1', 'old command', 'get_time', '{}', 'ok', 'old')",
        (old_ts,),
    )
    memory_store.record_activity(
        session_id="s1", transcript="today's command", tool="get_time", args={}, outcome="ok", speech="now",
    )

    deleted = memory_store.forget("today")

    assert deleted == 1
    remaining = memory_store._conn.execute("SELECT transcript FROM activity").fetchall()
    assert remaining == [("old command",)]


def test_forget_last_deletes_only_the_most_recent_row(memory_store: MemoryStore):
    memory_store.record_activity(
        session_id="s1", transcript="first", tool="get_time", args={}, outcome="ok", speech="a"
    )
    memory_store.record_activity(
        session_id="s1", transcript="second", tool="get_time", args={}, outcome="ok", speech="b"
    )

    deleted = memory_store.forget("last")

    assert deleted == 1
    remaining = [r[0] for r in memory_store._conn.execute("SELECT transcript FROM activity").fetchall()]
    assert remaining == ["first"]


def test_forget_all_clears_activity_and_artifacts(memory_store: MemoryStore):
    memory_store.record_activity(
        session_id="s1", transcript="x", tool="get_time", args={}, outcome="ok", speech="a"
    )
    memory_store.record_artifact(path="C:/a.docx", kind="docx", title="a.docx", source_transcript="x")

    memory_store.forget("all")

    assert memory_store._conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0] == 0
    assert memory_store._conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0


def test_forget_with_nothing_recorded_returns_zero(memory_store: MemoryStore):
    assert memory_store.forget("last") == 0
    assert memory_store.forget("today") == 0


def test_sessions_start_and_touch(memory_store: MemoryStore):
    memory_store.start_session("s1")
    memory_store.start_session("s1")  # idempotent, must not raise or duplicate
    memory_store.touch_session("s1")
    memory_store.touch_session("s1")

    row = memory_store._conn.execute(
        "SELECT command_count FROM sessions WHERE id = 's1'"
    ).fetchone()
    assert row == (2,)


def test_prune_older_than_removes_old_activity_only(memory_store: MemoryStore):
    old_ts = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    memory_store._conn.execute(
        "INSERT INTO activity (ts, session_id, transcript, tool, args_json, outcome, speech) "
        "VALUES (?, 's1', 'ancient', 'get_time', '{}', 'ok', 'a')",
        (old_ts,),
    )
    memory_store.record_activity(
        session_id="s1", transcript="recent", tool="get_time", args={}, outcome="ok", speech="b"
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    pruned = memory_store.prune_older_than(cutoff)

    assert pruned == 1
    remaining = [r[0] for r in memory_store._conn.execute("SELECT transcript FROM activity").fetchall()]
    assert remaining == ["recent"]
