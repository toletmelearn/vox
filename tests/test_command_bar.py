"""command_bar.py tests: CommandHistory and compute_hint are plain Python,
tested without a display. CommandBar itself (the Tkinter shell) is not
covered here - spec Section 13 tests never require a display."""
from __future__ import annotations

from vox.ui.command_bar import CommandHistory, compute_hint


def test_history_empty_returns_none():
    history = CommandHistory()
    assert history.older() is None
    assert history.newer() is None


def test_history_add_then_walk_older():
    history = CommandHistory()
    history.add("make a folder called Test")
    history.add("what's the time")
    assert history.older() == "what's the time"
    assert history.older() == "make a folder called Test"
    assert history.older() == "make a folder called Test"  # stops at the oldest


def test_history_walk_older_then_newer_returns_to_empty():
    history = CommandHistory()
    history.add("one")
    history.add("two")
    assert history.older() == "two"
    assert history.older() == "one"
    assert history.newer() == "two"
    assert history.newer() == ""  # walked past the newest back to a blank line


def test_history_caps_at_five_most_recent():
    history = CommandHistory(max_size=5)
    for i in range(8):
        history.add(f"command {i}")
    assert history.older() == "command 7"
    seen = [history.older() for _ in range(10)]
    assert "command 3" in seen  # the oldest of the last 5 (3, 4, 5, 6, 7) survives
    assert "command 2" not in seen  # evicted along with 0 and 1


def test_history_ignores_blank_submissions():
    history = CommandHistory()
    history.add("   ")
    assert history.older() is None


def test_history_add_resets_cursor():
    history = CommandHistory()
    history.add("first")
    history.older()
    history.add("second")
    assert history.older() == "second"


def test_compute_hint_empty_text_is_blank():
    assert compute_hint("") == ""
    assert compute_hint("   ") == ""


def test_compute_hint_shows_matched_tool():
    assert compute_hint("what's the time") == "-> get_time"


def test_compute_hint_shows_no_match_for_gibberish():
    hint = compute_hint("book me a flight to Goa")
    assert "no Tier 0 match" in hint


def test_compute_hint_shows_clarification_for_context_pronoun():
    hint = compute_hint("open it")
    assert "needs more info" in hint
