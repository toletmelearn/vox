"""open_target / play_on_target tools (spec Section 6A). Both resolve a
service name against the target catalogue with fuzzy matching, then run the
resolution ladder — no ad hoc app-vs-browser logic here."""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from yt_dlp import YoutubeDL

from vox.config import get_settings
from vox.memory.context import get_context
from vox.memory.store import get_memory_store
from vox.resolver.resolve import resolve_channel, resolve_target
from vox.resolver.targets import Target, TargetMatch, find_target
from vox.tools.registry import ToolResult, tool

logger = logging.getLogger("vox.tools.targets")

_VIDEO_ID_RE = re.compile(r"^[\w-]{6,20}$")


def _clarify_target(query: str, match: TargetMatch) -> ToolResult:
    if match.suggestions:
        options = " or ".join(match.suggestions)
        return ToolResult(ok=False, speech=f"I don't know {query}. Did you mean {options}?")
    return ToolResult(ok=False, speech=f"I don't know how to reach {query}.")


@tool(
    name="open_target",
    risk="medium",
    description=(
        "Open a known service or app such as YouTube, WhatsApp, Gmail, "
        "Spotify. Automatically picks the installed app, an already-open "
        "window, or the browser."
    ),
)
def open_target(target: str) -> ToolResult:
    match = find_target(target)
    if match.target is None:
        return _clarify_target(target, match)

    resolution = resolve_target(match.target, get_settings())
    if not resolution.ok:
        return ToolResult(ok=False, speech=f"Couldn't reach {match.target.display}.")

    context = get_context()
    context.last_target = match.target.key
    context.touch()
    return ToolResult(ok=True, speech=f"Opening {match.target.display}.")


def _youtube_video_id(query: str) -> str | None:
    try:
        with YoutubeDL(
            {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
        ) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
    except Exception:
        logger.warning("YouTube search failed for %r", query, exc_info=True)
        return None
    entries = (info or {}).get("entries") or []
    if not entries:
        return None
    video_id = entries[0].get("id")
    if not video_id or not _VIDEO_ID_RE.match(video_id):
        return None
    return str(video_id)


def _play_payload(target: Target, query: str) -> tuple[str | None, str] | None:
    """Builds (deep_link, web_url) for the specific thing being played.
    `None` means the search could not be resolved at all (only possible for
    YouTube, whose web_url must be an exact watch URL, never a bare search
    results page — spec Section 6A)."""
    if target.key == "youtube":
        video_id = _youtube_video_id(query)
        if video_id is None:
            return None
        return None, f"https://www.youtube.com/watch?v={video_id}"

    web_url = target.web_search_url.format(q=quote(query)) if target.web_search_url else target.web_url
    deep_link = f"{target.deep_link}search:{quote(query)}" if target.key == "spotify" and target.deep_link else None
    return deep_link, web_url


@tool(
    name="play_on_target",
    risk="safe",
    description=(
        "Search for and play something on a media service, e.g. a song on "
        "YouTube or Spotify."
    ),
)
def play_on_target(target: str, query: str) -> ToolResult:
    match = find_target(target)
    if match.target is None:
        return _clarify_target(target, match)

    payload = _play_payload(match.target, query)
    if payload is None:
        return ToolResult(ok=False, speech=f"Couldn't find {query} on {match.target.display}.")
    deep_link, web_url = payload

    resolution = resolve_channel(match.target, get_settings(), deep_link=deep_link, web_url=web_url)
    if not resolution.ok:
        return ToolResult(ok=False, speech=f"Couldn't play that on {match.target.display}.")

    context = get_context()
    context.last_target = match.target.key
    context.touch()
    return ToolResult(ok=True, speech=f"Playing {query} on {match.target.display}.")


@tool(
    name="rescan_apps",
    risk="safe",
    description="Forget cached results about which apps are installed, so the next command re-checks.",
)
def rescan_apps() -> ToolResult:
    get_memory_store().invalidate_app_cache()
    return ToolResult(ok=True, speech="Okay, I'll recheck installed apps next time.")
