"""The Target catalogue (spec Section 6A): data, not code — lives in
`targets.yaml` at the repo root, shipped with sensible defaults and directly
user-editable. This module only loads it and does fuzzy lookup; the
resolution ladder itself is `resolver/resolve.py`."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

TargetPreference = Literal["app", "web"]

# spec Section 6A: absorb Whisper mishears like "you tube"/"whats up" before
# falling back to a clarification.
_FUZZY_CUTOFF = 0.75


@dataclass(frozen=True)
class Target:
    key: str
    display: str
    aliases: list[str]
    deep_link: str | None
    web_url: str
    web_search_url: str | None
    window_title_match: list[str]
    windows_app_ids: list[str]
    process_names: list[str]
    prefer: TargetPreference = "app"


@dataclass(frozen=True)
class TargetMatch:
    target: Target | None
    # Display names of the closest catalogue entries, for a clarification
    # question. Empty when `target` is set, or when nothing was close enough
    # to even guess at.
    suggestions: list[str]


def load_targets(path: Path | None = None) -> dict[str, Target]:
    """Missing file -> empty catalogue (invariant 9: degrade, never brick;
    open_target/play_on_target just always clarify). A malformed one still
    raises, same policy as config.py's load_settings — a broken targets.yaml
    should be loud, not silently ignored."""
    if path is None:
        path = Path("targets.yaml")
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    catalogue: dict[str, Target] = {}
    for key, fields in raw.items():
        catalogue[key] = Target(
            key=key,
            display=fields.get("display", key.replace("_", " ").title()),
            aliases=list(fields.get("aliases") or []),
            deep_link=fields.get("deep_link"),
            web_url=fields["web_url"],
            web_search_url=fields.get("web_search_url"),
            window_title_match=list(fields.get("window_title_match") or []),
            windows_app_ids=list(fields.get("windows_app_ids") or []),
            process_names=list(fields.get("process_names") or []),
            prefer=fields.get("prefer", "app"),
        )
    return catalogue


_catalogue: dict[str, Target] | None = None


def get_target_catalogue() -> dict[str, Target]:
    global _catalogue
    if _catalogue is None:
        _catalogue = load_targets()
    return _catalogue


def set_target_catalogue(catalogue: dict[str, Target]) -> None:
    """Test hook."""
    global _catalogue
    _catalogue = catalogue


def reset_target_catalogue() -> None:
    global _catalogue
    _catalogue = None


def find_target(
    query: str, catalogue: dict[str, Target] | None = None, *, cutoff: float = _FUZZY_CUTOFF
) -> TargetMatch:
    """Exact key -> case-insensitive alias -> fuzzy (spec Section 6A:
    `difflib.get_close_matches`, cutoff 0.75) over keys and aliases
    together. Below cutoff, never guesses — returns the two closest names
    instead so the caller can ask rather than act."""
    catalogue = get_target_catalogue() if catalogue is None else catalogue
    q = query.strip().lower()

    if q in catalogue:
        return TargetMatch(target=catalogue[q], suggestions=[])

    lookup: dict[str, Target] = {}
    for target in catalogue.values():
        lookup[target.key] = target
        for alias in target.aliases:
            lookup[alias.strip().lower()] = target

    if q in lookup:
        return TargetMatch(target=lookup[q], suggestions=[])

    close = difflib.get_close_matches(q, lookup.keys(), n=1, cutoff=cutoff)
    if close:
        return TargetMatch(target=lookup[close[0]], suggestions=[])

    loose = difflib.get_close_matches(q, lookup.keys(), n=6, cutoff=0.0)
    suggestions: list[str] = []
    for name in loose:
        display = lookup[name].display
        if display not in suggestions:
            suggestions.append(display)
        if len(suggestions) == 2:
            break
    return TargetMatch(target=None, suggestions=suggestions)
