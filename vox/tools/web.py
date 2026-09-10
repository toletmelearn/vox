"""Web tools: search, YouTube resolution, URL opening, downloads. URL and
download rules are spec Section 6 (tools/web.py)."""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from yt_dlp import YoutubeDL

from vox.config import get_settings
from vox.platform import get_adapter
from vox.security.jail import JailViolation, resolve_in_jail, sanitize_filename
from vox.tools.registry import ToolResult, tool

logger = logging.getLogger("vox.tools.web")

_VIDEO_ID_RE = re.compile(r"^[\w-]{6,20}$")


class UrlValidationError(ValueError):
    """Raised by _validate_url; never propagates past a tool boundary."""


def _validate_url(url: str, blocked_hosts: list[str]) -> str:
    """Scheme must be http/https; host must not be private/loopback/
    link-local/reserved or in config.security.blocked_hosts. Rejects
    file://, data:, javascript: via the scheme check alone."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UrlValidationError(f"unsupported URL scheme: {parsed.scheme!r}")

    host = parsed.hostname
    if not host:
        raise UrlValidationError("URL has no host")
    if host.lower() == "localhost":
        raise UrlValidationError("localhost is blocked")
    if host.lower() in {h.lower() for h in blocked_hosts}:
        raise UrlValidationError(f"host is blocked: {host!r}")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        raise UrlValidationError(f"host resolves to a non-public address: {host!r}")

    return host


@tool(
    name="web_search",
    risk="safe",
    description="Open the default browser on a search results page.",
)
def web_search(query: str) -> ToolResult:
    url = f"https://www.google.com/search?q={quote(query)}"
    if not get_adapter().open_default_browser(url):
        return ToolResult(ok=False, speech="Couldn't open the browser.")
    return ToolResult(ok=True, speech=f"Searching for {query}.")


@tool(
    name="play_youtube",
    risk="safe",
    description="Find a YouTube video by description and open it in the browser.",
)
def play_youtube(query: str) -> ToolResult:
    try:
        with YoutubeDL(
            {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
        ) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
    except Exception:
        logger.warning("play_youtube search failed for %r", query, exc_info=True)
        return ToolResult(ok=False, speech="Couldn't search YouTube.")

    entries = (info or {}).get("entries") or []
    if not entries:
        return ToolResult(ok=False, speech=f"Couldn't find {query} on YouTube.")

    video_id = entries[0].get("id")
    if not video_id or not _VIDEO_ID_RE.match(video_id):
        return ToolResult(ok=False, speech="Couldn't find that on YouTube.")

    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    if not get_adapter().open_default_browser(watch_url):
        return ToolResult(ok=False, speech="Couldn't open the browser.")
    return ToolResult(ok=True, speech=f"Playing {query} on YouTube.")


@tool(
    name="open_url",
    risk="medium",
    description="Open a specific URL in the default browser.",
)
def open_url(url: str) -> ToolResult:
    settings = get_settings()
    try:
        _validate_url(url, settings.security.blocked_hosts)
    except UrlValidationError:
        logger.warning("open_url rejected %r", url, exc_info=True)
        return ToolResult(ok=False, speech="That URL isn't allowed.")

    if not get_adapter().open_default_browser(url):
        return ToolResult(ok=False, speech="Couldn't open the browser.")
    return ToolResult(ok=True, speech="Opening that page.")


@tool(
    name="download_file",
    risk="medium",
    description="Download a file from a URL into the downloads folder.",
)
def download_file(url: str, filename: str = "") -> ToolResult:
    settings = get_settings()
    try:
        _validate_url(url, settings.security.blocked_hosts)
    except UrlValidationError:
        logger.warning("download_file rejected %r", url, exc_info=True)
        return ToolResult(ok=False, speech="That URL isn't allowed.")

    if not filename:
        filename = Path(urlparse(url).path).name or "download"
    try:
        leaf = sanitize_filename(filename)
    except JailViolation:
        return ToolResult(ok=False, speech="That filename isn't allowed.")

    max_bytes = settings.security.max_download_mb * 1024 * 1024
    tmp_fd, tmp_path_str = tempfile.mkstemp()
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "wb") as tmp_file:
            with requests.get(url, stream=True, timeout=30) as response:
                response.raise_for_status()
                total = 0
                for chunk in response.iter_content(chunk_size=65536):
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError(
                            f"download exceeds max_download_mb ({settings.security.max_download_mb})"
                        )
                    tmp_file.write(chunk)
    except (requests.RequestException, ValueError, OSError):
        tmp_path.unlink(missing_ok=True)
        logger.warning("download_file failed for %r", url, exc_info=True)
        return ToolResult(ok=False, speech="The download failed.")

    dest = resolve_in_jail(leaf, parent_key="downloads")
    if dest.exists():
        tmp_path.unlink(missing_ok=True)
        return ToolResult(ok=False, speech=f"{leaf} already exists.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp_path), str(dest))
    return ToolResult(ok=True, speech=f"Downloaded {dest.name}.", artifact_path=str(dest))
