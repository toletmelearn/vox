"""Target-resolver Tier 0 patterns — open_target/play_on_target/
compose_whatsapp_message (spec Section 7, Phase 7). Split out of
tier0_grammar.py to keep that module under CLAUDE.md's 300-line guideline,
same precedent as tier0_hindi.py's language-alias split.

Built fresh on every call from the live target catalogue
(vox.resolver.targets.get_target_catalogue()) rather than a static compiled
list, since the catalogue is user-editable data (targets.yaml) that can
change between calls in tests."""
from __future__ import annotations

import re
from collections.abc import Callable
from re import Match

from vox.resolver.targets import get_target_catalogue
from vox.router.base import RouteResult, ToolCall

# Same filler-word tolerance as tier0_grammar's own _FILLER_INLINE -
# duplicated rather than imported to avoid a circular import between the
# two modules (tier0_grammar imports this module, not the other way round).
_FILLER_INLINE = r"(?:please\s+|just\s+|can you\s+)*"


def _call(name: str, args: dict[str, object]) -> RouteResult:
    return RouteResult(call=ToolCall(name=name, args=args), confidence=0.95, tier="tier0")


def _h_open_target(m: Match[str]) -> RouteResult:
    return _call("open_target", {"target": m.group("target").strip()})


def _h_play_on_target(m: Match[str]) -> RouteResult:
    return _call(
        "play_on_target", {"target": m.group("target").strip(), "query": m.group("query").strip()}
    )


def _h_compose_whatsapp_message(m: Match[str]) -> RouteResult:
    return _call(
        "compose_whatsapp_message",
        {"contact": m.group("contact").strip(), "message": m.group("message").strip()},
    )


def _h_rescan_apps(m: Match[str]) -> RouteResult:
    return _call("rescan_apps", {})


def _h_play_youtube_default(m: Match[str]) -> RouteResult:
    return _call("play_youtube", {"query": m.group("query").strip()})


def _target_alternation() -> str | None:
    """Every catalogue key and alias, longest first so a multi-word alias
    ("google drive") matches in full before a shorter one could shadow it.
    `None` when the catalogue is empty (a missing targets.yaml — invariant
    9: degrade, never brick; these patterns just don't match)."""
    catalogue = get_target_catalogue()
    if not catalogue:
        return None
    names: set[str] = set()
    for target in catalogue.values():
        names.add(target.key)
        names.update(alias.strip().lower() for alias in target.aliases)
    ordered = sorted(names, key=len, reverse=True)
    return "|".join(re.escape(n) for n in ordered)


def patterns() -> list[tuple[re.Pattern[str], Callable[[Match[str]], RouteResult]]]:
    """Called from tier0_grammar.route(), *after* its own static patterns -
    so the existing play_youtube patterns there keep priority for "on
    youtube" phrasing (spec Section 7 lists both; play_youtube's own yt-dlp
    resolution is the more specific, already-working behaviour). WhatsApp
    messaging patterns come first here since they're the most specific
    shape.

    The final entry is a deliberate default, not an oversight: a bare "play
    X" with no target word at all (spec Section 1's own worked example,
    "play Kishore Kumar songs", defaults to YouTube) must resolve here,
    deterministically, rather than falling through to Tier 1 - a real,
    live bug found by the user showed Tier 1 filling play_on_target's
    required `target` argument with a plausible-but-unrequested guess
    ("spotify") when nothing was said, since "spotify" is a genuinely valid
    catalogue key and no schema-level check can tell "valid" apart from
    "not what the user asked for." This entry only fires when nothing more
    specific matched first (it's last in this list, and everything above -
    plus tier0_grammar's own static "on youtube" patterns, tried before
    this module at all - already claims every phrasing that names a
    target). The negative lookahead excludes any tail shaped like "... on
    <word>" even when <word> isn't a real catalogue entry ("play X on
    flipkart") - swallowing "on flipkart" into a YouTube search query would
    silently misinterpret a request that named a target, just one this
    catalogue doesn't know; that case should escalate to Tier 1 rather than
    guess YouTube. Unlike the catalogue-driven entries above, this one
    doesn't need targets.yaml at all, so it's included even when the
    catalogue is empty/missing (invariant 9: degrade, never brick) -
    "play X" should still default to YouTube on a machine with no resolver
    catalogue configured."""
    default_play_pattern = (
        re.compile(rf"^{_FILLER_INLINE}play\s+(?!.*\bon\s+\S+$)(?P<query>.+)$", re.IGNORECASE),
        _h_play_youtube_default,
    )

    alt = _target_alternation()
    if alt is None:
        return [default_play_pattern]
    return [
        (
            re.compile(
                rf"^{_FILLER_INLINE}(?:go to |open )?whatsapp\s+(?:and\s+)?(?:send|message|msg)"
                rf"(?:\s+a\s+message)?\s+(?:to\s+)?(?P<contact>\w+)\s+(?:saying|that)\s+(?P<message>.+)$",
                re.IGNORECASE,
            ),
            _h_compose_whatsapp_message,
        ),
        (
            re.compile(
                rf"^{_FILLER_INLINE}(?:message|msg|text)\s+(?P<contact>\w+)\s+on\s+whatsapp\s+"
                rf"(?:saying\s+)?(?P<message>.+)$",
                re.IGNORECASE,
            ),
            _h_compose_whatsapp_message,
        ),
        (
            re.compile(
                rf"^{_FILLER_INLINE}(?:go to |open )?(?P<target>{alt})\s+(?:and\s+)?play\s+(?P<query>.+)$",
                re.IGNORECASE,
            ),
            _h_play_on_target,
        ),
        (
            re.compile(
                rf"^{_FILLER_INLINE}play\s+(?P<query>.+?)\s+on\s+(?P<target>{alt})$",
                re.IGNORECASE,
            ),
            _h_play_on_target,
        ),
        (
            re.compile(rf"^{_FILLER_INLINE}(?:go to|open|launch)\s+(?P<target>{alt})$", re.IGNORECASE),
            _h_open_target,
        ),
        (
            re.compile(r"^rescan apps$", re.IGNORECASE),
            _h_rescan_apps,
        ),
        default_play_pattern,
    ]
