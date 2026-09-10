"""System tools (spec Section 6, tools/system.py)."""
from __future__ import annotations

from datetime import datetime

from vox.platform import get_adapter
from vox.platform.base import UnsupportedCapability
from vox.security.jail import resolve_in_jail
from vox.tools.registry import ToolResult, tool


@tool(name="get_time", risk="safe", description="Say the current date and time.")
def get_time() -> ToolResult:
    now = datetime.now()
    speech = now.strftime("It's %I:%M %p on %A, %B %d.")
    return ToolResult(ok=True, speech=speech)


@tool(name="set_volume", risk="safe", description="Set system volume 0-100.")
def set_volume(level: int) -> ToolResult:
    clamped = max(0, min(100, level))
    try:
        ok = get_adapter().set_volume(clamped)
    except UnsupportedCapability:
        return ToolResult(ok=False, speech="Volume control isn't available on this system.")
    if not ok:
        return ToolResult(ok=False, speech="Couldn't change the volume.")
    return ToolResult(ok=True, speech=f"Volume set to {clamped}.")


@tool(name="take_screenshot", risk="safe", description="Save a screenshot.")
def take_screenshot() -> ToolResult:
    filename = datetime.now().strftime("Screenshot_%Y%m%d_%H%M%S.png")
    dest = resolve_in_jail(filename, parent_key="desktop")
    try:
        saved = get_adapter().screenshot(dest)
    except UnsupportedCapability:
        return ToolResult(ok=False, speech="Screenshots aren't available on this system.")
    if not saved:
        return ToolResult(ok=False, speech="Couldn't take a screenshot.")
    return ToolResult(ok=True, speech="Screenshot saved.", artifact_path=str(dest))


@tool(name="lock_screen", risk="destructive", description="Lock the workstation.")
def lock_screen() -> ToolResult:
    try:
        ok = get_adapter().lock_screen()
    except UnsupportedCapability:
        return ToolResult(ok=False, speech="Locking isn't available on this system.")
    if not ok:
        return ToolResult(ok=False, speech="Couldn't lock the screen.")
    return ToolResult(ok=True, speech="Locking the screen.")
