"""The 4-step target resolution ladder (spec Section 6A). Every "reach a
service" tool (open_target, play_on_target, compose_whatsapp_message) goes
through here instead of hand-rolling its own app-vs-browser logic."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from vox.config import Settings
from vox.platform import get_adapter
from vox.resolver import detect
from vox.resolver.targets import Target

logger = logging.getLogger("vox.resolver.resolve")

ResolutionMethod = Literal["focused_existing", "launched_app", "existing_browser", "default_browser"]


@dataclass(frozen=True)
class Resolution:
    ok: bool
    method: ResolutionMethod | None = None
    handle: int | str | None = None
    reason: str | None = None


def resolve_target(target: Target, settings: Settings) -> Resolution:
    """The full ladder: open window -> installed app -> existing browser ->
    default browser, opening the target's own `web_url`/`deep_link` with no
    payload. Used by `open_target` — "go to YouTube" just needs to reach
    YouTube, reusing an already-open tab when there is one."""
    adapter = get_adapter()
    caps = adapter.capabilities()

    if settings.resolver.reuse_open_window and {"list_windows", "focus_window"} <= caps:
        handle = detect.find_open_window(target)
        if handle is not None and adapter.focus_window(handle):
            return Resolution(ok=True, method="focused_existing", handle=handle)

    return resolve_channel(target, settings, deep_link=target.deep_link, web_url=target.web_url)


def resolve_channel(
    target: Target, settings: Settings, *, deep_link: str | None, web_url: str
) -> Resolution:
    """Steps 2-4 only, opening the exact `deep_link`/`web_url` the caller
    supplies. `play_on_target` and `compose_whatsapp_message` need to open a
    *specific* new URL (a search payload, a pre-filled chat) — there is no
    way to navigate an already-focused window to a different URL without
    synthesising input, so both deliberately skip Step 1 and call this
    directly instead of `resolve_target`. See DECISIONS.md."""
    adapter = get_adapter()
    caps = adapter.capabilities()

    if settings.resolver.prefer_native_app and target.prefer == "app" and "launch" in caps:
        installed = detect.detect_installed(target, settings)
        if installed is not None:
            uri = deep_link or installed
            if adapter.launch(uri):
                return Resolution(ok=True, method="launched_app")

    browser_exe = detect.preferred_running_browser_exe(settings)
    if browser_exe is not None and "launch" in caps and adapter.launch(browser_exe, [web_url]):
        return Resolution(ok=True, method="existing_browser")

    if "open_default_browser" in caps and adapter.open_default_browser(web_url):
        return Resolution(ok=True, method="default_browser")

    return Resolution(ok=False, reason=f"no way to reach {target.display} on this system")
