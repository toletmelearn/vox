"""tools/memory_tools.py tests. The audit.db byte-identical check (spec
Section 10 Phase 6 acceptance) calls forget_activity directly, not through
the guard layer - going through execute_tool_call would itself add a
pending+updated row to audit.db, which is expected guard-layer behaviour
but would defeat this specific test's point (see memory/store.py's
module docstring: forget_activity must never touch audit.db itself)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from vox.security.audit import AuditLog
from vox.tools.memory_tools import find_recent_artifact, forget_activity, recall_activity


def test_recall_activity_returns_deterministic_speech_with_no_model_call(memory_store, mocker):
    # A real assertion that no model is reachable from this path: nothing in
    # this test constructs an Ollama/Anthropic client at all, and
    # summarize_activity's only dependency is the DB (spec Section 6C).
    would_raise = mocker.patch("vox.router.tier1_local.route", side_effect=AssertionError("must not call Tier 1"))

    result = recall_activity(query="today", days=7)

    assert result.ok
    would_raise.assert_not_called()


def test_find_recent_artifact_matches_by_description(memory_store):
    memory_store.record_artifact(
        path="C:/Documents/Physics Notes.docx", kind="docx", title="Physics Notes.docx",
        source_transcript="make a word file about physics",
    )
    memory_store.record_artifact(
        path="C:/Documents/Grocery List.txt", kind="txt", title="Grocery List.txt", source_transcript="x"
    )

    result = find_recent_artifact(description="physics")

    assert result.ok
    assert result.artifact_path == "C:/Documents/Physics Notes.docx"


def test_find_recent_artifact_no_match_still_ok(memory_store):
    result = find_recent_artifact(description="nonexistent")
    assert result.ok
    assert result.artifact_path is None


def test_forget_activity_speech_mentions_it_does_not_touch_the_security_log(memory_store):
    memory_store.record_activity(
        session_id="s1", transcript="x", tool="get_time", args={}, outcome="ok", speech="a"
    )
    result = forget_activity(scope="all")
    assert result.ok
    assert "not the security log" in result.speech


def test_forget_activity_leaves_audit_db_byte_identical(memory_store, jail_settings, tmp_path):
    audit_path = Path(jail_settings.paths.state_dir).expanduser() / "audit.db"
    audit = AuditLog(audit_path)
    audit.write_pending(
        transcript="make a folder called Test", tool="create_folder", args={"name": "Test"},
        risk="safe", tier="text",
    )
    audit.close()

    before_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()

    memory_store.record_activity(
        session_id="s1", transcript="what did I do today", tool="get_time", args={}, outcome="ok", speech="a"
    )
    forget_activity(scope="all")

    after_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    assert before_hash == after_hash
