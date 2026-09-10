"""Tier 0 grammar: regex rules tried in order, first match wins. Instant,
offline, never guesses — a match always returns confidence 0.95 (spec
Section 7). Patterns needing Context (the pronoun/last-artifact rules) are
registered but always return a clarification, since Context itself is a
Phase 6 deliverable; see DECISIONS.md.

Patterns for open_target/play_on_target/compose_whatsapp_message/
recall_activity are deferred to Phase 7/6, when those tools exist — matching
them here would just dispatch to a tool the registry doesn't have yet.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from re import Match

from vox.config import get_settings
from vox.router.base import RouteResult, ToolCall

_FILLER_PREFIX = re.compile(r"^(?:hey|ok|okay|please|computer)[\s,]+", re.IGNORECASE)
_FILLER_INLINE = r"(?:please\s+|just\s+|can you\s+)*"
_PARENT_ALT = r"(?P<parent>desktop|documents|downloads|workdir)"
_APP_ALT = r"(?P<app>chrome|edge|firefox|notepad|word|excel|calculator|explorer|vscode|terminal)"

# (raw phrase, canonical English verb). Word order matches English for all
# of these, so a straight substitution is enough — "banao"/"bana do"
# ("make") is the one Hindi verb whose word order is reversed for folder
# creation, handled by a dedicated pattern below instead (spec Section 6F).
_HINDI_VERB_ALIASES: list[tuple[str, str]] = [
    (r"\bkhol do\b", "open"),
    (r"\bkholo\b", "open"),
    (r"\bbaja do\b", "play"),
    (r"\bchalao\b", "play"),
    (r"\bsearch karo\b", "search"),
    (r"\bdhoondo\b", "search"),
    (r"\bbhej do\b", "send"),
    (r"\bbhejo\b", "send"),
    (r"\bband karo\b", "stop"),
]


def _cleanup(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"[.!?]+$", "", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    while True:
        stripped = _FILLER_PREFIX.sub("", cleaned)
        if stripped == cleaned:
            break
        cleaned = stripped
    return cleaned


def _apply_hindi_aliases(text: str) -> str:
    for pattern, replacement in _HINDI_VERB_ALIASES:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _normalize_spoken_filename(name: str) -> str:
    """Whisper artefact cleanup (spec Section 7): 'dot txt' -> '.txt', etc."""
    name = re.sub(r"\s+dot\s+txt\b", ".txt", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+underscore\s+", "_", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+dash\s+", "-", name, flags=re.IGNORECASE)
    return name.strip()


def _call(name: str, args: dict[str, object]) -> RouteResult:
    return RouteResult(call=ToolCall(name=name, args=args), confidence=0.95, tier="tier0")


def _clarify(question: str) -> RouteResult:
    return RouteResult(call=None, confidence=0.0, tier="tier0", clarification=question)


def _h_web_search(m: Match[str]) -> RouteResult:
    return _call("web_search", {"query": m.group("query").strip()})


def _h_play_youtube(m: Match[str]) -> RouteResult:
    return _call("play_youtube", {"query": m.group("query").strip()})


def _h_open_url(m: Match[str]) -> RouteResult:
    return _call("open_url", {"url": m.group("url").strip()})


def _h_download_file(m: Match[str]) -> RouteResult:
    return _call("download_file", {"url": m.group("url").strip()})


def _h_create_folder(m: Match[str]) -> RouteResult:
    name = _normalize_spoken_filename(m.group("name").strip())
    parent = (m.group("parent") or "desktop").lower()
    return _call("create_folder", {"name": name, "parent": parent})


def _h_create_folder_hindi(m: Match[str]) -> RouteResult:
    name = _normalize_spoken_filename(m.group("name").strip())
    return _call("create_folder", {"name": name, "parent": "desktop"})


def _h_create_text_file(m: Match[str]) -> RouteResult:
    name = _normalize_spoken_filename(m.group("name").strip())
    parent = (m.group("parent") or "desktop").lower()
    return _call("create_text_file", {"name": name, "parent": parent})


def _h_create_word_document(m: Match[str]) -> RouteResult:
    filename = m.group("filename").strip()
    return _call(
        "create_word_document",
        {"filename": filename, "title": filename, "sections": []},
    )


def _h_create_pdf(m: Match[str]) -> RouteResult:
    filename = m.group("filename").strip()
    return _call("create_pdf", {"filename": filename, "title": filename, "paragraphs": []})


def _h_open_app(m: Match[str]) -> RouteResult:
    return _call("open_app", {"app": m.group("app").lower()})


def _h_get_time(m: Match[str]) -> RouteResult:
    return _call("get_time", {})


def _h_set_volume(m: Match[str]) -> RouteResult:
    return _call("set_volume", {"level": int(m.group("level"))})


def _h_take_screenshot(m: Match[str]) -> RouteResult:
    return _call("take_screenshot", {})


def _h_lock_screen(m: Match[str]) -> RouteResult:
    return _call("lock_screen", {})


def _h_open_context_pronoun(m: Match[str]) -> RouteResult:
    return _clarify("Which file do you mean?")


def _h_convert_context_pronoun(m: Match[str]) -> RouteResult:
    return _clarify("Which file do you mean?")


_PATTERNS: list[tuple[re.Pattern[str], Callable[[Match[str]], RouteResult]]] = [
    (
        re.compile(rf"^{_FILLER_INLINE}(?:search for|search|google|look up)\s+(?P<query>.+)$", re.IGNORECASE),
        _h_web_search,
    ),
    (
        re.compile(rf"^{_FILLER_INLINE}play\s+(?P<query>.+?)\s+(?:on\s+youtube|youtube)$", re.IGNORECASE),
        _h_play_youtube,
    ),
    (
        re.compile(rf"^{_FILLER_INLINE}(?:play|open)\s+youtube\s+(?P<query>.+)$", re.IGNORECASE),
        _h_play_youtube,
    ),
    (
        re.compile(rf"^{_FILLER_INLINE}open\s+(?P<url>https?://\S+)$", re.IGNORECASE),
        _h_open_url,
    ),
    (
        re.compile(
            rf"^{_FILLER_INLINE}download(?:\s+(?:this|the))?(?:\s+file)?\s+(?P<url>https?://\S+)$",
            re.IGNORECASE,
        ),
        _h_download_file,
    ),
    (
        re.compile(
            rf"^{_FILLER_INLINE}(?:make|create|new)\s+(?:a\s+)?word\s+(?:document|file)\s+"
            rf"(?:called|named)\s+(?P<filename>.+)$",
            re.IGNORECASE,
        ),
        _h_create_word_document,
    ),
    (
        re.compile(
            rf"^{_FILLER_INLINE}(?:make|create|new)\s+(?:a\s+)?pdf\s+(?:called|named)\s+(?P<filename>.+)$",
            re.IGNORECASE,
        ),
        _h_create_pdf,
    ),
    (
        re.compile(
            rf"^{_FILLER_INLINE}(?:make|create|new)\s+(?:a\s+)?(?:new\s+)?folder\s+(?:called|named)?\s*"
            rf"(?P<name>.+?)(?:\s+(?:on|in)\s+{_PARENT_ALT})?$",
            re.IGNORECASE,
        ),
        _h_create_folder,
    ),
    (
        re.compile(
            rf"^{_FILLER_INLINE}(?:make|create|new)\s+(?:a\s+)?(?:new\s+)?(?:text\s+)?file\s+(?:called|named)?\s*"
            rf"(?P<name>.+?)(?:\s+(?:on|in)\s+{_PARENT_ALT})?$",
            re.IGNORECASE,
        ),
        _h_create_text_file,
    ),
    (
        re.compile(rf"^{_FILLER_INLINE}open\s+{_APP_ALT}$", re.IGNORECASE),
        _h_open_app,
    ),
    (
        re.compile(r"^(?:what'?s the |tell me the )?time(?: now)?$", re.IGNORECASE),
        _h_get_time,
    ),
    (
        re.compile(r"^(?:set |turn )?volume(?: to)?\s+(?P<level>\d{1,3})$", re.IGNORECASE),
        _h_set_volume,
    ),
    (
        re.compile(r"^(?:take (?:a )?)?screenshot$", re.IGNORECASE),
        _h_take_screenshot,
    ),
    (
        re.compile(r"^lock(?: the)?\s+(?:screen|computer|pc)$", re.IGNORECASE),
        _h_lock_screen,
    ),
    (
        re.compile(r"^open\s+(?:it|that|the file)$", re.IGNORECASE),
        _h_open_context_pronoun,
    ),
    (
        re.compile(r"^(?:make|convert|turn)\s+(?:that|it|this)\s+(?:in)?to\s+(?:a\s+)?pdf$", re.IGNORECASE),
        _h_convert_context_pronoun,
    ),
]


# Reversed word order ("<name> ke naam se ek folder banao") — spec Section
# 6F's literal example. Gated separately since it isn't fixed by the simple
# verb substitution above (English word order stays verb-first).
_HINDI_PATTERNS: list[tuple[re.Pattern[str], Callable[[Match[str]], RouteResult]]] = [
    (
        re.compile(
            r"^(?P<name>.+?)\s*(?:ke naam se\s*)?(?:ek\s+)?folder\s+(?:banao|bana do)$",
            re.IGNORECASE,
        ),
        _h_create_folder_hindi,
    ),
]


def route(text: str) -> RouteResult:
    cleaned = _cleanup(text)

    hindi_aliases_enabled = get_settings().stt.hindi_aliases
    if hindi_aliases_enabled:
        for pattern, handler in _HINDI_PATTERNS:
            match = pattern.match(cleaned)
            if match:
                return handler(match)
        cleaned = _apply_hindi_aliases(cleaned)

    for pattern, handler in _PATTERNS:
        match = pattern.match(cleaned)
        if match:
            return handler(match)

    return RouteResult(call=None, confidence=0.0, tier="none")
