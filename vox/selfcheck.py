"""Startup self-check (spec Section 8.9): verify jail roots, whisper/Piper/
Ollama/hotkey availability, print a green/red table. Split out of app.py to
keep it under the 300-line-per-module guideline (CLAUDE.md) - app.py still
calls this as part of bootstrap()."""
from __future__ import annotations

import shutil
from pathlib import Path

import psutil
from rich.console import Console
from rich.table import Table

from vox.config import Settings
from vox.platform import get_adapter
from vox.platform.base import UnsupportedCapability
from vox.router import tier1_local
from vox.security.jail import jail_roots

_EXPECTED_CAPABILITIES = {
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

    if settings.tier1.enabled:
        tier1_ok = tier1_local.is_available()
        status = "[green]ollama reachable[/]" if tier1_ok else "[red]unavailable - Tier 0 only[/]"
    else:
        status = "[yellow]disabled in config[/]"
    table.add_row(f"tier 1: {settings.tier1.model}", status)

    for label, chord in (("voice", settings.hotkeys.voice), ("text", settings.hotkeys.text)):
        try:
            hotkey_ok = adapter.verify_hotkey_available(chord)
            status = "[green]available[/]" if hotkey_ok else "[red]already claimed by another app[/]"
        except UnsupportedCapability:
            status = "[yellow]cannot verify on this platform[/]"
        table.add_row(f"hotkey: {label} ({chord})", status)

    present = adapter.capabilities()
    for cap in sorted(_EXPECTED_CAPABILITIES):
        status = "[green]present[/]" if cap in present else "[red]absent[/]"
        table.add_row(f"capability: {cap}", status)

    console.print(table)
