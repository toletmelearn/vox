"""Adapter that supports nothing. Used in tests so the suite never touches a
real OS, and as the runtime fallback on an unsupported platform (invariant 9:
degrade, never brick)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from vox.platform.base import UnsupportedCapability, WindowInfo


class NullAdapter:
    name = "null"

    def list_windows(self) -> list[WindowInfo]:
        raise UnsupportedCapability("list_windows is not available")

    def focus_window(self, handle: int | str) -> bool:
        raise UnsupportedCapability("focus_window is not available")

    def find_installed_app(self, target: Any) -> str | None:
        raise UnsupportedCapability("find_installed_app is not available")

    def launch(self, exe_or_uri: str, args: list[str] | None = None) -> bool:
        raise UnsupportedCapability("launch is not available")

    def running_processes(self) -> set[str]:
        raise UnsupportedCapability("running_processes is not available")

    def open_default_browser(self, url: str) -> bool:
        raise UnsupportedCapability("open_default_browser is not available")

    def running_browsers(self) -> list[str]:
        raise UnsupportedCapability("running_browsers is not available")

    def set_volume(self, level: int) -> bool:
        raise UnsupportedCapability("set_volume is not available")

    def lock_screen(self) -> bool:
        raise UnsupportedCapability("lock_screen is not available")

    def screenshot(self, dest: Path) -> bool:
        raise UnsupportedCapability("screenshot is not available")

    def notify(self, title: str, body: str) -> None:
        raise UnsupportedCapability("notify is not available")

    def open_path(self, path: Path) -> bool:
        raise UnsupportedCapability("open_path is not available")

    def os_build(self) -> str:
        return "unknown"

    def cpu_supports_avx2(self) -> bool:
        return False

    def capabilities(self) -> set[str]:
        return set()
