"""System tools. Phase 1 ships get_time only; set_volume, take_screenshot,
and lock_screen land in Phase 2 (spec Section 10)."""
from __future__ import annotations

from datetime import datetime

from vox.tools.registry import ToolResult, tool


@tool(name="get_time", risk="safe", description="Say the current date and time.")
def get_time() -> ToolResult:
    now = datetime.now()
    speech = now.strftime("It's %I:%M %p on %A, %B %d.")
    return ToolResult(ok=True, speech=speech)
