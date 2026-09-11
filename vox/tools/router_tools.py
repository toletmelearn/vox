"""Tier 1's legal escape hatch (spec Section 7): when a request is
ambiguous or not covered by any other tool, the model must call this
instead of fabricating a call. Registered like any other tool so it goes
through the normal guard/audit path in app.py - no special-casing needed
in the router."""
from __future__ import annotations

from vox.tools.registry import ToolResult, tool


@tool(
    name="ask_clarification",
    risk="safe",
    description=(
        "Ask the user a short clarifying question instead of guessing. Use "
        "this whenever the request is ambiguous, or isn't something any "
        "other available tool can do."
    ),
)
def ask_clarification(question: str) -> ToolResult:
    return ToolResult(ok=True, speech=question)
