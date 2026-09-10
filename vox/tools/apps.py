"""App launch tool. Backed by config.apps only — no PATH search, no
os.system (spec Section 6, tools/apps.py)."""
from __future__ import annotations

from vox.config import get_settings
from vox.platform import get_adapter
from vox.tools.registry import ToolResult, tool


@tool(
    name="open_app",
    risk="medium",
    description="Launch a known desktop application by friendly name.",
)
def open_app(app: str) -> ToolResult:
    exe = get_settings().apps.get(app.strip().lower())
    if exe is None:
        return ToolResult(ok=False, speech=f"I don't know how to open {app}.")

    if not get_adapter().launch(exe):
        return ToolResult(ok=False, speech=f"Couldn't open {app}.")
    return ToolResult(ok=True, speech=f"Opening {app}.")
