"""memory/context.py tests: the in-process Context that makes 'make that a
PDF' work (spec Section 6C). Expiry is checked against time.monotonic(),
mocked here rather than really sleeping."""
from __future__ import annotations

from vox.memory.context import Context, get_context, reset_context, set_context


def test_fresh_context_has_no_last_artifact():
    context = Context()
    assert context.last_artifact is None
    assert not context.is_expired(15)


def test_set_last_artifact_and_read_it_back():
    context = Context()
    context.set_last_artifact("C:/Documents/Notes.docx", "docx", "Notes.docx")
    assert context.last_artifact is not None
    assert context.last_artifact.path == "C:/Documents/Notes.docx"
    assert context.last_artifact.kind == "docx"


def test_is_expired_after_the_ttl(mocker):
    import time

    context = Context()
    context.touch()
    mocker.patch("vox.memory.context.time.monotonic", return_value=time.monotonic() + 16 * 60)
    assert context.is_expired(15)


def test_is_not_expired_within_the_ttl(mocker):
    import time

    context = Context()
    context.touch()
    mocker.patch("vox.memory.context.time.monotonic", return_value=time.monotonic() + 5 * 60)
    assert not context.is_expired(15)


def test_start_new_session_clears_everything(mocker):
    context = Context()
    context.set_last_artifact("C:/a.docx", "docx", "a.docx")
    context.add_turn("make a docx", "create_word_document", "Created a.docx.")
    old_session_id = context.session_id

    context.start_new_session()

    assert context.session_id != old_session_id
    assert context.last_artifact is None
    assert len(context.recent_turns) == 0


def test_recent_turns_caps_at_max_size():
    context = Context(recent_turns_max=6)
    for i in range(10):
        context.add_turn(f"turn {i}", "get_time", "ok")
    assert len(context.recent_turns) == 6
    assert context.recent_turns[0].transcript == "turn 4"
    assert context.recent_turns[-1].transcript == "turn 9"


def test_singleton_accessors_round_trip():
    reset_context()
    first = get_context()
    assert get_context() is first

    fresh = Context()
    set_context(fresh)
    assert get_context() is fresh

    reset_context()
    assert get_context() is not fresh
