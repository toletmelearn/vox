"""File and folder tools. Every path argument goes through resolve_in_jail —
see CLAUDE.md invariant 2 and spec Section 6 (vox/tools/files.py)."""
from __future__ import annotations

import logging

import send2trash

from vox.platform import get_adapter
from vox.platform.base import UnsupportedCapability
from vox.security.jail import jail_roots, resolve_in_jail, sanitize_filename
from vox.tools.registry import ToolResult, tool

logger = logging.getLogger("vox.tools.files")


@tool(
    name="create_folder",
    risk="safe",
    description="Create a new folder. Use for 'make a folder called X'.",
)
def create_folder(name: str, parent: str = "desktop") -> ToolResult:
    resolved = resolve_in_jail(name, parent_key=parent)
    leaf = sanitize_filename(resolved.name)
    final = resolved.with_name(leaf)
    if final.exists():
        return ToolResult(ok=False, speech=f"{leaf} already exists.")
    final.mkdir(parents=True, exist_ok=False)
    return ToolResult(
        ok=True, speech=f"Created folder {leaf}.", artifact_path=str(final)
    )


@tool(
    name="create_text_file",
    risk="safe",
    description="Create a plain text file with optional content.",
)
def create_text_file(name: str, content: str = "", parent: str = "desktop") -> ToolResult:
    resolved = resolve_in_jail(name, parent_key=parent)
    leaf = sanitize_filename(resolved.name)
    if "." not in leaf:
        leaf = f"{leaf}.txt"
    final = resolved.with_name(leaf)
    if final.exists():
        return ToolResult(ok=False, speech=f"{leaf} already exists.")
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_text(content, encoding="utf-8")
    return ToolResult(
        ok=True, speech=f"Created file {leaf}.", artifact_path=str(final)
    )


@tool(
    name="open_path",
    risk="safe",
    description="Open a file or folder in the system file manager or default app.",
)
def open_path(path: str) -> ToolResult:
    resolved = resolve_in_jail(path)
    if not resolved.exists():
        return ToolResult(ok=False, speech="That doesn't exist.")
    try:
        opened = get_adapter().open_path(resolved)
    except UnsupportedCapability:
        return ToolResult(ok=False, speech="Opening files isn't supported here.")
    if not opened:
        return ToolResult(ok=False, speech=f"Couldn't open {resolved.name}.")
    return ToolResult(ok=True, speech=f"Opened {resolved.name}.")


@tool(
    name="find_files",
    risk="safe",
    description="Search for files by name fragment inside the jailed roots.",
)
def find_files(query: str, limit: int = 20) -> ToolResult:
    needle = query.lower()
    matches: list[str] = []
    for root in jail_roots():
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if needle in path.name.lower():
                matches.append(str(path))
                if len(matches) >= limit:
                    break
        if len(matches) >= limit:
            break

    if not matches:
        return ToolResult(ok=True, speech=f"No files found matching {query}.")
    return ToolResult(
        ok=True,
        speech=f"Found {len(matches)} file{'s' if len(matches) != 1 else ''}.",
        detail="\n".join(matches),
    )


@tool(
    name="move_to_trash",
    risk="destructive",
    description="Send a file or folder to the recycle bin. Always confirmed.",
)
def move_to_trash(path: str) -> ToolResult:
    resolved = resolve_in_jail(path)
    if not resolved.exists():
        return ToolResult(ok=False, speech="That doesn't exist.")
    try:
        send2trash.send2trash(str(resolved))
    except OSError:
        logger.warning("move_to_trash failed for %r", resolved, exc_info=True)
        return ToolResult(ok=False, speech=f"Couldn't delete {resolved.name}.")
    return ToolResult(ok=True, speech=f"Moved {resolved.name} to the recycle bin.")
