"""Installation/open-window detection for the target resolver (spec Section
6A: "Is it already open?" / "Is the native app installed?"). Split from
resolve.py so the ladder itself stays small; nothing in this module performs
the actual open/launch — that's resolve.py's job."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from vox.config import Settings
from vox.memory.store import get_memory_store
from vox.platform import get_adapter
from vox.platform.base import UnsupportedCapability
from vox.resolver.targets import Target


def find_open_window(target: Target) -> int | str | None:
    """Step 1: live window-title match — never cached (spec Section 6A:
    "Window-open detection is never cached — it must be live")."""
    adapter = get_adapter()
    needles = [n.lower() for n in target.window_title_match]
    if not needles:
        return None
    for window in adapter.list_windows():
        title = window.title.lower()
        if any(needle in title for needle in needles):
            return window.handle
    return None


def detect_installed(target: Target, settings: Settings) -> str | None:
    """Step 2's "is it installed" check, in the spec's literal order:
    running process -> registry/Start Menu (cached) -> config.apps map.
    Returns something `launch()`-able, or a bare process name when only a
    running process was found and no exe path is known (the caller prefers
    the target's own deep_link over this anyway, when one exists). `None`
    means "couldn't tell it's installed" — the caller falls back to a
    browser."""
    adapter = get_adapter()
    caps = adapter.capabilities()

    if "running_processes" in caps and target.process_names:
        running = {p.lower() for p in adapter.running_processes()}
        if any(p.lower() in running for p in target.process_names):
            return target.process_names[0]

    exe = cached_find_installed_app(target, settings)
    if exe:
        return exe

    exe = settings.apps.get(target.key)
    if exe:
        return exe
    for alias in target.aliases:
        candidate = settings.apps.get(alias.strip().lower().replace(" ", ""))
        if candidate:
            return candidate
    return None


def cached_find_installed_app(target: Target, settings: Settings) -> str | None:
    """The slow check (registry walk / Start Menu scan) — spec Section 6A:
    "Cache results in the memory store with a 24-hour TTL, keyed by
    target." A second `open_target` call within the TTL returns the cached
    row without ever calling `adapter.find_installed_app` again."""
    store = get_memory_store()
    cached = store.get_app_cache(target.key)
    ttl = timedelta(hours=settings.resolver.install_cache_ttl_hours)
    if cached is not None and (datetime.now(timezone.utc) - cached.checked_at) < ttl:
        return cached.exe_path if cached.installed else None

    adapter = get_adapter()
    exe: str | None = None
    if "find_installed_app" in adapter.capabilities():
        try:
            exe = adapter.find_installed_app(target)
        except UnsupportedCapability:
            exe = None
    store.set_app_cache(target.key, installed=exe is not None, exe_path=exe)
    return exe


def preferred_running_browser_exe(settings: Settings) -> str | None:
    """Step 3 needs the *executable* of whichever browser is already
    running, so it can be launched with the URL as an argument (spec:
    "open the web_url in that browser rather than the system default").
    Matches by executable stem against config.apps values rather than a
    hardcoded per-OS process-name table, so this stays free of
    platform-specific literals (CLAUDE.md invariant 4) — platform/*.py's
    own `running_browsers()` already returns the right vocabulary for its
    OS (`chrome.exe` on Windows, `chrome`/`google-chrome` on Linux)."""
    adapter = get_adapter()
    if "running_browsers" not in adapter.capabilities():
        return None
    running_stems = {Path(p).stem.lower() for p in adapter.running_browsers()}
    if not running_stems:
        return None

    preferred_key = settings.resolver.preferred_browser
    if preferred_key:
        exe = settings.apps.get(preferred_key)
        if exe and Path(exe).stem.lower() in running_stems:
            return exe

    for exe in settings.apps.values():
        if Path(exe).stem.lower() in running_stems:
            return exe
    return None
