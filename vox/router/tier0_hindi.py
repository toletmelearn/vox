"""Romanised Hindi/Hinglish aliasing for Tier 0 (spec Section 6F). Split out
of tier0_grammar.py to keep that module under CLAUDE.md's 300-line
guideline - this is the whole of the language-alias layer, deliberately
minimal per the spec's own scoping (see DECISIONS.md)."""
from __future__ import annotations

import re
from collections.abc import Callable
from re import Match

from vox.router.base import RouteResult, ToolCall

# (raw phrase, canonical English verb). Word order matches English for all
# of these, so a straight substitution is enough — "banao"/"bana do"
# ("make") is the one Hindi verb whose word order is reversed for folder
# creation, handled by a dedicated pattern below instead (spec Section 6F).
VERB_ALIASES: list[tuple[str, str]] = [
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


def apply_verb_aliases(text: str) -> str:
    for pattern, replacement in VERB_ALIASES:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _normalize_spoken_filename(name: str) -> str:
    """Same Whisper-artefact cleanup as tier0_grammar's private helper of
    the same name (spec Section 7: 'dot txt' -> '.txt', etc). Duplicated
    rather than imported across the two modules - four lines of regex isn't
    worth a circular import between them."""
    name = re.sub(r"\s+dot\s+txt\b", ".txt", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+underscore\s+", "_", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+dash\s+", "-", name, flags=re.IGNORECASE)
    return name.strip()


def _h_create_folder_hindi(m: Match[str]) -> RouteResult:
    name = _normalize_spoken_filename(m.group("name").strip())
    return RouteResult(
        call=ToolCall(name="create_folder", args={"name": name, "parent": "desktop"}),
        confidence=0.95,
        tier="tier0",
    )


# Reversed word order ("<name> ke naam se ek folder banao") — spec Section
# 6F's literal example. Gated separately since it isn't fixed by the simple
# verb substitution above (English word order stays verb-first).
PATTERNS: list[tuple[re.Pattern[str], Callable[[Match[str]], RouteResult]]] = [
    (
        re.compile(
            r"^(?P<name>.+?)\s*(?:ke naam se\s*)?(?:ek\s+)?folder\s+(?:banao|bana do)$",
            re.IGNORECASE,
        ),
        _h_create_folder_hindi,
    ),
]
