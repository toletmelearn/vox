"""End-to-end text pipeline tests matching the Phase 1 acceptance criteria
verbatim (spec Section 10)."""
from __future__ import annotations

from pathlib import Path

from vox.app import handle_text


def _row_count(audit_log) -> int:
    return audit_log._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def test_make_folder_creates_it_and_writes_one_audit_row(jail_settings, audit_log):
    result = handle_text("make a folder called Test")
    assert result.ok
    assert Path(jail_settings.paths.desktop, "Test").is_dir()
    assert _row_count(audit_log) == 1

    row = audit_log._conn.execute("SELECT status, tool FROM events").fetchone()
    assert row == ("executed", "create_folder")


def test_make_folder_traversal_is_rejected_no_folder_no_execution(jail_settings, audit_log):
    result = handle_text("make a folder called ../../evil")
    assert not result.ok

    row = audit_log._conn.execute("SELECT status, tool FROM events").fetchone()
    assert row == ("rejected", "create_folder")

    # nowhere outside the jailed tmp_path tree should have anything created
    assert not (Path(jail_settings.paths.desktop).parent.parent / "evil").exists()


def test_unrecognised_text_returns_clarification_without_audit_row(jail_settings, audit_log):
    # Tier 1 is exercised separately (mocked) in tests/test_tier1.py; here we
    # want the plain "no tier could handle this" path, so disable it rather
    # than let it reach for the real Ollama server (spec Section 13: no test
    # may create a network connection).
    jail_settings.tier1.enabled = False
    result = handle_text("book me a flight to Goa")
    assert not result.ok
    assert _row_count(audit_log) == 0


def _fake_convert_docx_to_pdf(src, dest_dir):
    (dest_dir / f"{src.stem}.pdf").write_text("fake pdf", encoding="utf-8")
    return True


def test_make_word_file_then_make_that_a_pdf_resolves_context_with_no_llm_call(
    jail_settings, audit_log, memory_store, mocker
):
    """Phase 6 acceptance: 'make a Word file called Notes' then 'make that a
    PDF' works - the second command resolves 'it' from context with no LLM
    call."""
    mocker.patch("vox.tools.documents.shutil.which", return_value=None)  # force the adapter fallback path
    mocker.patch(
        "vox.tools.documents.get_adapter"
    ).return_value.convert_docx_to_pdf.side_effect = _fake_convert_docx_to_pdf
    tier1_route = mocker.patch(
        "vox.router.tier1_local.route", side_effect=AssertionError("Tier 1 must not be called")
    )

    first = handle_text("make a word file called Notes")
    assert first.ok
    assert first.artifact_path is not None
    assert first.artifact_path.endswith("Notes.docx")

    second = handle_text("make that a pdf")

    tier1_route.assert_not_called()
    assert second.ok, second.speech
    assert second.artifact_path is not None
    assert second.artifact_path.endswith("Notes.pdf")
    assert _row_count(audit_log) == 2


def test_make_that_a_pdf_past_the_context_ttl_asks_which_file_instead_of_acting(
    jail_settings, audit_log, memory_store, mocker
):
    """Phase 6 acceptance: the same pair, with the clock advanced past
    context_ttl_minutes, returns a clarification instead of acting - and
    never reaches for Tier 1 (spec Section 13: no test may open a network
    connection; an expired context-pronoun match must stay a Tier 0
    clarification, never a bare no-match that would escalate)."""
    import time

    mocker.patch("vox.tools.documents.shutil.which", return_value=None)
    tier1_route = mocker.patch(
        "vox.router.tier1_local.route", side_effect=AssertionError("Tier 1 must not be called")
    )

    first = handle_text("make a word file called Notes")
    assert first.ok

    jail_settings.memory.context_ttl_minutes = 15
    mocker.patch("vox.memory.context.time.monotonic", return_value=time.monotonic() + 16 * 60)

    second = handle_text("make that a pdf")

    tier1_route.assert_not_called()
    assert not second.ok
    assert "which file" in second.speech.lower()
    # No second tool call was made, so still only the first command's row.
    assert _row_count(audit_log) == 1


def test_what_did_i_do_today_returns_deterministic_summary_with_no_model_call(
    jail_settings, audit_log, memory_store, mocker
):
    """Phase 6 acceptance: 'what did I do today' returns a deterministic
    DB-backed summary. No model call is made."""
    tier1_route = mocker.patch(
        "vox.router.tier1_local.route", side_effect=AssertionError("Tier 1 must not be called")
    )

    handle_text("what's the time")
    result = handle_text("what did I do today")

    tier1_route.assert_not_called()
    assert result.ok
    assert "today" in result.speech.lower()


def test_store_transcripts_false_writes_no_spoken_text_to_disk(jail_settings, audit_log, memory_store):
    """Phase 6 acceptance: with store_transcripts: false, no spoken text is
    written to disk anywhere."""
    jail_settings.memory.store_transcripts = False

    handle_text("make a folder called Secret Project")

    transcripts_dir = Path(jail_settings.paths.state_dir).expanduser() / "transcripts"
    assert not transcripts_dir.exists() or list(transcripts_dir.glob("*.jsonl")) == []

    row = memory_store._conn.execute("SELECT transcript FROM activity").fetchone()
    assert row is not None
    assert row[0] == "create_folder"  # tool name only, not the real transcript
    assert "Secret Project" not in row[0]


def test_memory_store_failure_degrades_gracefully_instead_of_crashing(
    jail_settings, audit_log, memory_store, mocker
):
    """Invariant 9 ('degrade, never brick'): a real memory-store failure
    must not crash a command whose own tool call already succeeded, on
    either the voice or text path - both share execute_tool_call. Forces
    the real memory_store to raise (not a mocked-away record_execution) so
    this exercises the actual failure this guards against."""
    mocker.patch.object(memory_store, "record_activity", side_effect=OSError("disk full"))

    result = handle_text("make a folder called Resilient")

    assert result.ok
    assert Path(jail_settings.paths.desktop, "Resilient").is_dir()
