"""Tier 0 grammar coverage: ≥30 phrasings across all patterns, with expected
tool + args (spec Section 10, Phase 2 acceptance). Pure routing — no jail,
no filesystem, no network; route() only reads settings.stt.hindi_aliases."""
from __future__ import annotations

from vox.router.base import RouteResult
from vox.router.tier0_grammar import route

# (phrase, expected_tool_name_or_None, expected_args_or_None)
# expected_tool_name of "__clarify__" means call is None but a clarification
# is expected; None/None means no match at all (falls through to Tier 1).
CASES: list[tuple[str, str | None, dict[str, object] | None]] = [
    # web_search
    ("search for Laravel queue tutorial", "web_search", {"query": "Laravel queue tutorial"}),
    ("search Laravel", "web_search", {"query": "Laravel"}),
    ("google best pizza near me", "web_search", {"query": "best pizza near me"}),
    ("look up how tall is Everest", "web_search", {"query": "how tall is Everest"}),
    ("please search for python tutorials", "web_search", {"query": "python tutorials"}),
    # play_youtube
    ("play Kishore Kumar songs on youtube", "play_youtube", {"query": "Kishore Kumar songs"}),
    ("play Munni Badnaam Hui youtube", "play_youtube", {"query": "Munni Badnaam Hui"}),
    ("play youtube Munni Badnaam Hui", "play_youtube", {"query": "Munni Badnaam Hui"}),
    ("open youtube lofi hip hop radio", "play_youtube", {"query": "lofi hip hop radio"}),
    # open_url
    ("open https://example.com/page", "open_url", {"url": "https://example.com/page"}),
    # download_file
    ("download https://example.com/a.zip", "download_file", {"url": "https://example.com/a.zip"}),
    ("download this file https://example.com/notes.pdf", "download_file", {"url": "https://example.com/notes.pdf"}),
    ("download the file https://example.com/x.csv", "download_file", {"url": "https://example.com/x.csv"}),
    # create_folder
    ("make a folder called Test", "create_folder", {"name": "Test", "parent": "desktop"}),
    (
        "make a folder called Physics Notes on desktop",
        "create_folder",
        {"name": "Physics Notes", "parent": "desktop"},
    ),
    ("create folder named Backups in documents", "create_folder", {"name": "Backups", "parent": "documents"}),
    ("just create a new folder called Scratch", "create_folder", {"name": "Scratch", "parent": "desktop"}),
    ("can you make a folder called Logs in downloads", "create_folder", {"name": "Logs", "parent": "downloads"}),
    # create_text_file
    ("make a text file called todo", "create_text_file", {"name": "todo", "parent": "desktop"}),
    ("create a file named notes in documents", "create_text_file", {"name": "notes", "parent": "documents"}),
    # create_word_document / create_pdf (explicit filename, no topic)
    (
        "make a word document called Draft Report",
        "create_word_document",
        {"filename": "Draft Report", "title": "Draft Report", "sections": []},
    ),
    (
        "create a word file named Meeting Notes",
        "create_word_document",
        {"filename": "Meeting Notes", "title": "Meeting Notes", "sections": []},
    ),
    (
        "make a pdf called Draft Report",
        "create_pdf",
        {"filename": "Draft Report", "title": "Draft Report", "paragraphs": []},
    ),
    # a topic-phrased request must NOT match Tier 0 (needs content generation)
    ("make a word file about the water cycle", None, None),
    # a compound/multi-step command must NOT match Tier 0 - a second buried
    # imperative ("...and inside this make a word file...") means the whole
    # tail would otherwise be swallowed into the name (real live bug, see
    # DECISIONS.md "Compound command silently became the folder name")
    (
        "make a folder on desktop and named it Amit Saxena and inside this "
        "make a word file and in the word file make a question paper of "
        "class 10 with help of chatgpt",
        None,
        None,
    ),
    ("create a file named notes and then open chrome", None, None),
    ("make a word document called Draft Report and download https://x.com/a.zip", None, None),
    # open_app
    ("open chrome", "open_app", {"app": "chrome"}),
    ("open notepad", "open_app", {"app": "notepad"}),
    ("open vscode", "open_app", {"app": "vscode"}),
    # get_time
    ("what's the time", "get_time", {}),
    ("tell me the time now", "get_time", {}),
    ("time", "get_time", {}),
    # set_volume
    ("set volume to 40", "set_volume", {"level": 40}),
    ("volume 75", "set_volume", {"level": 75}),
    # take_screenshot
    ("take a screenshot", "take_screenshot", {}),
    ("screenshot", "take_screenshot", {}),
    # lock_screen
    ("lock the screen", "lock_screen", {}),
    ("lock pc", "lock_screen", {}),
    # stop_action (spec Section 1: "stop"/"cancel" aborts the running action)
    ("stop", "stop_action", {}),
    ("cancel", "stop_action", {}),
    ("cancel that", "stop_action", {}),
    ("band karo", "stop_action", {}),  # Hindi alias -> "stop"
    # context pronouns - this module stays context-free by design (see its
    # module docstring): a match always pairs a clarification with
    # RouteResult.context_action; only app.py resolves that against the real
    # Context singleton, so route() alone always returns a clarification here.
    ("open it", "__clarify__", None),
    ("make that a pdf", "__clarify__", None),
    ("make that into a pdf", "__clarify__", None),
    ("convert this to a pdf", "__clarify__", None),
    # recall_activity (spec Section 7's literal pattern; Phase 6's memory
    # store now exists, so this dispatches directly - no model call)
    ("what did I do today", "recall_activity", {"query": "what did I do today", "days": 7}),
    ("what did I do yesterday", "recall_activity", {"query": "what did I do yesterday", "days": 7}),
    ("what did you do this week", "recall_activity", {"query": "what did you do this week", "days": 7}),
    # Hindi / Hinglish aliases (spec Section 6F)
    ("kholo chrome", "open_app", {"app": "chrome"}),
    ("chalao youtube lofi beats", "play_youtube", {"query": "lofi beats"}),
    ("dhoondo python tutorials", "web_search", {"query": "python tutorials"}),
    ("Physics Notes ke naam se ek folder banao", "create_folder", {"name": "Physics Notes", "parent": "desktop"}),
    ("todo folder bana do", "create_folder", {"name": "todo", "parent": "desktop"}),
    # leading wake-filler stripped
    ("hey, what's the time", "get_time", {}),
    ("computer take a screenshot", "take_screenshot", {}),
    # unmatched -> no route at all (Tier 1 territory, Phase 4)
    ("book me a flight to Goa", None, None),
]


def test_grammar_has_at_least_30_cases():
    assert len(CASES) >= 30


def test_grammar_coverage(jail_settings):
    for phrase, expected_tool, expected_args in CASES:
        result: RouteResult = route(phrase)

        if expected_tool == "__clarify__":
            assert result.call is None, phrase
            assert result.clarification is not None, phrase
            continue

        if expected_tool is None:
            assert result.call is None, phrase
            assert result.clarification is None, phrase
            continue

        assert result.call is not None, f"{phrase!r} did not match any pattern"
        assert result.call.name == expected_tool, phrase
        assert result.confidence == 0.95
        assert result.tier == "tier0"
        if expected_args is not None:
            assert result.call.args == expected_args, phrase
