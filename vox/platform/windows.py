"""Windows adapter: win32 APIs, ctypes, and stdlib only. No pycaw/comtypes —
they are not in the spec's pinned dependency list (Section 3), so set_volume
degrades to "unsupported" rather than shipping an imprecise hack. See
DECISIONS.md."""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

import psutil
import win32con
import win32gui

from vox.platform.base import UnsupportedCapability, WindowInfo

logger = logging.getLogger("vox.platform.windows")

_BROWSER_PROCESSES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}

# https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-isprocessorfeaturepresent
_PF_AVX2_INSTRUCTIONS_AVAILABLE = 40


class WindowsAdapter:
    name = "windows"

    def list_windows(self) -> list[WindowInfo]:
        results: list[WindowInfo] = []

        def _cb(hwnd: int, _: object) -> bool:
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                results.append(WindowInfo(handle=hwnd, title=win32gui.GetWindowText(hwnd)))
            return True

        win32gui.EnumWindows(_cb, None)
        return results

    def focus_window(self, handle: int | str) -> bool:
        try:
            hwnd = int(handle)
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            logger.warning("focus_window failed", exc_info=True)
            return False

    def find_installed_app(self, target: Any) -> str | None:
        # Registry App Paths / Start Menu scan lands with the resolver in
        # Phase 7, once resolver/targets.py defines Target.
        raise UnsupportedCapability("find_installed_app is not implemented yet")

    def launch(self, exe_or_uri: str, args: list[str] | None = None) -> bool:
        try:
            if "://" in exe_or_uri:
                os.startfile(exe_or_uri)  # noqa: S606 - not a shell string, a fixed URI
                return True
            subprocess.Popen([exe_or_uri, *(args or [])])
            return True
        except OSError:
            logger.warning("launch failed for %r", exe_or_uri, exc_info=True)
            return False

    def running_processes(self) -> set[str]:
        return {p.info["name"] for p in psutil.process_iter(["name"]) if p.info["name"]}

    def open_default_browser(self, url: str) -> bool:
        return webbrowser.open(url)

    def running_browsers(self) -> list[str]:
        running = self.running_processes()
        return sorted(running & _BROWSER_PROCESSES)

    def set_volume(self, level: int) -> bool:
        raise UnsupportedCapability(
            "set_volume needs Core Audio (pycaw/comtypes), not in the pinned deps"
        )

    def lock_screen(self) -> bool:
        try:
            ctypes.windll.user32.LockWorkStation()
            return True
        except OSError:
            logger.warning("lock_screen failed", exc_info=True)
            return False

    def screenshot(self, dest: Path) -> bool:
        try:
            from PIL import ImageGrab  # type: ignore[import-not-found]

            ImageGrab.grab().save(dest)
            return True
        except Exception:
            logger.warning("screenshot failed", exc_info=True)
            return False

    def notify(self, title: str, body: str) -> None:
        # Real balloon notifications are wired through the pystray tray icon
        # in Phase 5 (spec 3A.1: pystray only, no WinRT toast). Until the
        # tray exists there is no icon to attach a balloon to.
        logger.info("notify: %s - %s", title, body)

    def open_path(self, path: Path) -> bool:
        try:
            os.startfile(str(path))  # noqa: S606 - path already jail-validated by caller
            return True
        except OSError:
            logger.warning("open_path failed for %r", path, exc_info=True)
            return False

    def os_build(self) -> str:
        build = sys.getwindowsversion().build
        if build >= 22000:
            return f"Windows 11 (build {build})"
        return f"Windows 10 (build {build})"

    def cpu_supports_avx2(self) -> bool:
        try:
            return bool(
                ctypes.windll.kernel32.IsProcessorFeaturePresent(
                    _PF_AVX2_INSTRUCTIONS_AVAILABLE
                )
            )
        except OSError:
            return False

    def capabilities(self) -> set[str]:
        caps = {
            "list_windows",
            "focus_window",
            "launch",
            "running_processes",
            "open_default_browser",
            "running_browsers",
            "lock_screen",
            "open_path",
            "notify",
        }
        try:
            import PIL  # noqa: F401  # type: ignore[import-not-found]

            caps.add("screenshot")
        except ImportError:
            pass
        return caps
