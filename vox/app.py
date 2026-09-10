"""Wires config, logging, the platform adapter, and the guard/audit layer
together. Owns the startup self-check and the --text entry path."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

import psutil
from rich.console import Console
from rich.table import Table

import vox.tools  # noqa: F401 - import populates REGISTRY
from vox.config import Settings, get_settings
from vox.logging_setup import setup_logging
from vox.platform import get_adapter
from vox.router import tier0_grammar
from vox.router.base import ToolCall
from vox.security.audit import get_audit_log
from vox.security.jail import JailViolation, jail_roots
from vox.tools.registry import REGISTRY, ToolResult

logger = logging.getLogger("vox.app")


def execute_tool_call(call: ToolCall, *, transcript: str, tier: str = "text") -> ToolResult:
    """Guard layer: write the audit row before execution, run the tool
    through jail validation, update the row after. JailViolation is the only
    exception allowed to propagate out of a tool (spec Section 12); it is
    caught here and recorded as 'rejected'."""
    registered = REGISTRY.get(call.name)
    if registered is None:
        return ToolResult(ok=False, speech="I don't have that tool.")

    audit = get_audit_log()
    row_id = audit.write_pending(
        transcript=transcript,
        tool=call.name,
        args=call.args,
        risk=registered.risk,
        tier=tier,
    )
    start = time.monotonic()
    try:
        validated = registered.args_model(**call.args)
        result = registered.fn(**validated.model_dump())
    except JailViolation as exc:
        audit.update_status(row_id, status="rejected", error=str(exc))
        return ToolResult(ok=False, speech="That location isn't allowed.")
    except Exception as exc:  # noqa: BLE001 - tools must not raise; this is the backstop
        logger.error("tool %s raised unexpectedly", call.name, exc_info=True)
        audit.update_status(row_id, status="failed", error=str(exc))
        return ToolResult(ok=False, speech="Something went wrong.")

    duration_ms = int((time.monotonic() - start) * 1000)
    audit.update_status(
        row_id,
        status="executed" if result.ok else "failed",
        error=None if result.ok else result.detail,
        duration_ms=duration_ms,
    )
    return result


def handle_text(text: str) -> ToolResult:
    """Escalation logic (spec Section 7): Tier 0 first; Tier 1/2 land in
    Phase 4, so anything Tier 0 doesn't resolve is a plain "didn't
    understand" for now."""
    route_result = tier0_grammar.route(text)
    if route_result.clarification is not None:
        return ToolResult(ok=False, speech=route_result.clarification)
    if route_result.call is None:
        return ToolResult(ok=False, speech="I didn't understand that.")
    return execute_tool_call(route_result.call, transcript=text, tier=route_result.tier)


def run_self_check(settings: Settings) -> None:
    adapter = get_adapter()
    console = Console()
    table = Table(title="vox startup self-check")
    table.add_column("Check")
    table.add_column("Status")

    for root in jail_roots():
        try:
            root.mkdir(parents=True, exist_ok=True)
            ok = root.exists() and root.is_dir()
        except OSError:
            ok = False
        table.add_row(f"jail root: {root}", "[green]ok[/]" if ok else "[red]missing/unwritable[/]")

    table.add_row("OS", adapter.os_build())
    table.add_row("AVX2", "[green]present[/]" if adapter.cpu_supports_avx2() else "[red]absent[/]")

    ram_gb = psutil.virtual_memory().total / (1024**3)
    table.add_row("RAM", f"{ram_gb:.1f} GB")

    workdir = Path(settings.paths.workdir).expanduser()
    free_gb = shutil.disk_usage(workdir).free / (1024**3)
    table.add_row("Free disk (workdir volume)", f"{free_gb:.1f} GB")

    all_caps = {
        "list_windows",
        "focus_window",
        "launch",
        "running_processes",
        "open_default_browser",
        "running_browsers",
        "set_volume",
        "lock_screen",
        "screenshot",
        "notify",
        "open_path",
    }
    present = adapter.capabilities()
    for cap in sorted(all_caps):
        status = "[green]present[/]" if cap in present else "[red]absent[/]"
        table.add_row(f"capability: {cap}", status)

    console.print(table)


def bootstrap() -> Settings:
    settings = get_settings()
    setup_logging(settings)
    run_self_check(settings)
    return settings
