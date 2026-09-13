"""Linux adapter: X11 via wmctrl/xdotool where present, degrading capabilities
under Wayland per spec 3A.3. Uses stdlib + psutil only; no new pip deps for
volume/lock/notify — those shell out to system binaries if installed."""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import webbrowser
from pathlib import Path
from typing import Any

import psutil

from vox.platform.base import UnsupportedCapability, WindowInfo

logger = logging.getLogger("vox.platform.linux")

_BROWSER_PROCESSES = {"chrome", "google-chrome", "chromium", "firefox", "brave", "opera"}


def _is_x11() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() != "wayland"


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


class LinuxAdapter:
    name = "linux"

    def list_windows(self) -> list[WindowInfo]:
        if not _is_x11() or not _have("wmctrl"):
            raise UnsupportedCapability("window enumeration needs X11 + wmctrl")
        out = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, check=False)
        windows = []
        for line in out.stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4:
                windows.append(WindowInfo(handle=parts[0], title=parts[3]))
        return windows

    def focus_window(self, handle: int | str) -> bool:
        if not _is_x11() or not _have("wmctrl"):
            raise UnsupportedCapability("window focus needs X11 + wmctrl")
        result = subprocess.run(["wmctrl", "-i", "-a", str(handle)], check=False)
        return result.returncode == 0

    def find_installed_app(self, target: Any) -> str | None:
        """No registry/Start Menu equivalent on Linux; best-effort via
        `shutil.which` against `target.process_names` — Linux binaries are
        usually just their process name on PATH, unlike Windows' App
        Paths/Start Menu indirection."""
        for name in getattr(target, "process_names", None) or []:
            candidate = shutil.which(str(name))
            if candidate:
                return candidate
        return None

    def launch(self, exe_or_uri: str, args: list[str] | None = None) -> bool:
        try:
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
        return sorted(self.running_processes() & _BROWSER_PROCESSES)

    def set_volume(self, level: int) -> bool:
        if _have("pactl"):
            result = subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"], check=False
            )
            return result.returncode == 0
        raise UnsupportedCapability("set_volume needs pactl on PATH")

    def lock_screen(self) -> bool:
        for cmd in (["loginctl", "lock-session"], ["xdg-screensaver", "lock"]):
            if _have(cmd[0]):
                return subprocess.run(cmd, check=False).returncode == 0
        raise UnsupportedCapability("lock_screen needs loginctl or xdg-screensaver")

    def screenshot(self, dest: Path) -> bool:
        for cmd in (["gnome-screenshot", "-f", str(dest)], ["scrot", str(dest)]):
            if _have(cmd[0]):
                return subprocess.run(cmd, check=False).returncode == 0
        raise UnsupportedCapability("screenshot needs gnome-screenshot or scrot")

    def notify(self, title: str, body: str) -> None:
        if _have("notify-send"):
            subprocess.run(["notify-send", title, body], check=False)
        else:
            logger.info("notify: %s - %s", title, body)

    def open_path(self, path: Path) -> bool:
        if _have("xdg-open"):
            return subprocess.run(["xdg-open", str(path)], check=False).returncode == 0
        raise UnsupportedCapability("open_path needs xdg-open on PATH")

    def convert_docx_to_pdf(self, src: Path, dest_dir: Path) -> bool:
        # LibreOffice (checked directly via `soffice` in tools/documents.py)
        # is the only supported path on Linux; there is no COM equivalent.
        raise UnsupportedCapability("convert_docx_to_pdf needs LibreOffice's soffice")

    def verify_hotkey_available(self, chord: str) -> bool:
        # X11's XGrabKey could implement a real probe; deferred (not
        # observed as a problem on Linux yet, unlike the Windows case this
        # method exists to catch). Callers must treat UnsupportedCapability
        # as "can't verify" and proceed, not as a hard failure.
        raise UnsupportedCapability("verify_hotkey_available needs XGrabKey (not implemented)")

    def restrict_directory_to_current_user(self, path: Path) -> bool:
        try:
            path.chmod(0o700)
            return True
        except OSError:
            logger.warning("restrict_directory_to_current_user failed for %r", path, exc_info=True)
            return False

    def os_build(self) -> str:
        return f"Linux {platform.release()} ({'X11' if _is_x11() else 'Wayland'})"

    def cpu_supports_avx2(self) -> bool:
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as f:
                return "avx2" in f.read()
        except OSError:
            return False

    def capabilities(self) -> set[str]:
        caps = {
            "launch",
            "running_processes",
            "open_default_browser",
            "running_browsers",
            "restrict_directory_to_current_user",
            "find_installed_app",
        }
        if _is_x11() and _have("wmctrl"):
            caps |= {"list_windows", "focus_window"}
        if _have("pactl"):
            caps.add("set_volume")
        if _have("loginctl") or _have("xdg-screensaver"):
            caps.add("lock_screen")
        if _have("gnome-screenshot") or _have("scrot"):
            caps.add("screenshot")
        if _have("notify-send"):
            caps.add("notify")
        if _have("xdg-open"):
            caps.add("open_path")
        return caps
