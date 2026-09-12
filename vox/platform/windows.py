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

import ntsecuritycon
import psutil
import pythoncom
import win32api
import win32com.client
import win32con
import win32gui
import win32process
import win32security
from PIL import ImageGrab

from vox.platform.base import UnsupportedCapability, WindowInfo

logger = logging.getLogger("vox.platform.windows")

_BROWSER_PROCESSES = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}

# https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-isprocessorfeaturepresent
_PF_AVX2_INSTRUCTIONS_AVAILABLE = 40

# https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-registerhotkey
_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT = 0x0004
_MOD_WIN = 0x0008
_MOD_NOREPEAT = 0x4000
_PROBE_HOTKEY_ID = 0xBEEF  # arbitrary; only ever held for the duration of one probe call

_VK_NAMED = {"space": 0x20, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "enter": 0x0D}


def _parse_win_chord(chord: str) -> tuple[int, int]:
    """Parse 'ctrl+shift+space' into (modifier flags, virtual-key code) for
    RegisterHotKey. Separate from capture.py's parse_chord (pynput
    Key/KeyCode groups) — this one speaks the Win32 API's vocabulary."""
    mods = 0
    vk: int | None = None
    for raw_token in chord.lower().split("+"):
        token = raw_token.strip()
        if token == "ctrl":
            mods |= _MOD_CONTROL
        elif token == "alt":
            mods |= _MOD_ALT
        elif token == "shift":
            mods |= _MOD_SHIFT
        elif token in ("win", "cmd"):
            mods |= _MOD_WIN
        elif token in _VK_NAMED:
            vk = _VK_NAMED[token]
        elif len(token) == 1:
            vk = ord(token.upper())
        else:
            raise ValueError(f"unrecognised hotkey token: {token!r}")
    if vk is None:
        raise ValueError(f"chord has no non-modifier key: {chord!r}")
    return mods, vk


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
            # SetForegroundWindow (and ShowWindow's SW_RESTORE) require a
            # true top-level window. Tkinter's `winfo_id()` - the handle
            # command_bar.py passes here for its own just-created window -
            # returns the HWND of an internal "TkChild" control nested
            # inside the real top-level "TkTopLevel" window, not that
            # top-level window itself. Confirmed live: calling
            # SetForegroundWindow on that child hwnd fails every time,
            # returning FALSE with GetLastError() left at 0 - Windows
            # doesn't set an error code for this rejection, which is
            # exactly pywin32's "No error message is available". Walking up
            # to the real root via GetAncestor(GA_ROOT) before doing
            # anything fixes it; verified live both against a bare new
            # window and against a genuinely different foreground process
            # (notepad.exe) beforehand.
            hwnd = win32gui.GetAncestor(hwnd, win32con.GA_ROOT) or hwnd
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            self._force_foreground(hwnd)
            return True
        except Exception:
            logger.warning("focus_window failed", exc_info=True)
            return False

    def _force_foreground(self, hwnd: int) -> None:
        """Plain `SetForegroundWindow` is denied silently by Windows unless
        the calling thread already shares an input queue with whichever
        thread currently owns the foreground window - confirmed live with a
        scripted open/click/close loop against the command bar (a Tk window
        created on a background thread in response to a global hotkey): in
        2 of 5 rounds, a real click landed on the new window but
        `GetForegroundWindow()` still named the previous window afterward,
        leaving the entry with no real OS keyboard focus so Escape/Return
        never reached it even though Tk's own `focus_set()` had already
        "succeeded". `AttachThreadInput` is the documented Win32 workaround:
        it makes this thread and the foreground thread share one input
        queue for the duration of the call, which satisfies the check
        `SetForegroundWindow` uses to decide whether to honour the request.
        Callers must pass a real top-level hwnd (see `focus_window`'s
        GetAncestor(GA_ROOT) resolution) - SetForegroundWindow silently
        refuses a child window handle regardless of this workaround."""
        fg_hwnd = win32gui.GetForegroundWindow()
        fg_thread = win32process.GetWindowThreadProcessId(fg_hwnd)[0] if fg_hwnd else 0
        current_thread = win32api.GetCurrentThreadId()
        attached = bool(fg_thread and fg_thread != current_thread)
        if attached:
            win32process.AttachThreadInput(current_thread, fg_thread, True)
        try:
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                win32process.AttachThreadInput(current_thread, fg_thread, False)

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
            ImageGrab.grab().save(dest)
            return True
        except OSError:
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

    def convert_docx_to_pdf(self, src: Path, dest_dir: Path) -> bool:
        """Word COM automation (spec Section 6, documents.py fallback order).
        Only reached when LibreOffice's `soffice` isn't on PATH."""
        pythoncom.CoInitialize()
        word = None
        try:
            word = win32com.client.DispatchEx("Word.Application")  # type: ignore[no-untyped-call]
            word.Visible = False
            doc = word.Documents.Open(str(src))
            try:
                dest = dest_dir / f"{src.stem}.pdf"
                doc.SaveAs2(str(dest), FileFormat=17)
            finally:
                doc.Close(False)
            return True
        except Exception:
            logger.warning("convert_docx_to_pdf failed for %r", src, exc_info=True)
            return False
        finally:
            if word is not None:
                word.Quit()
            pythoncom.CoUninitialize()

    def verify_hotkey_available(self, chord: str) -> bool:
        """Real OS-level check (spec Section 6E: "pynput registration can
        fail silently... verify it took"). RegisterHotKey claims the chord
        exclusively at the OS level; if another application already holds
        it (confirmed on this dev machine: the Claude desktop app intercepts
        ctrl+alt+space before vox's listener ever sees it), this fails
        immediately and loudly instead of us silently assuming success.
        Registers and immediately unregisters — this is a probe, not the
        runtime mechanism (push-to-talk hold/release still comes from the
        low-level pynput Listener in audio/capture.py, since WM_HOTKEY has
        no hold/release semantics)."""
        try:
            mods, vk = _parse_win_chord(chord)
        except ValueError:
            logger.warning("could not parse hotkey %r for verification", chord, exc_info=True)
            return False

        user32 = ctypes.windll.user32
        ok = bool(user32.RegisterHotKey(None, _PROBE_HOTKEY_ID, mods | _MOD_NOREPEAT, vk))
        if ok:
            user32.UnregisterHotKey(None, _PROBE_HOTKEY_ID)
        return ok

    def restrict_directory_to_current_user(self, path: Path) -> bool:
        """ACL granting only the current user (spec Section 6C: '~/.vox/
        ... on Windows set an ACL granting only the current user'). Builds a
        fresh DACL with a single ACE rather than shelling out to `icacls`,
        whose /grant syntax is locale-dependent; pywin32 is already a pinned
        dependency (Section 3).

        The SID comes from the *process token* (SE_TOKEN_USER), not from
        `LookupAccountName(GetUserName())`: on at least one real environment
        this project was built and tested on, that name-based lookup
        returned the machine/domain SID with the final user RID missing
        (`S-1-5-21-x-y-z` instead of `S-1-5-21-x-y-z-1001`) - a *different*,
        unprivileged principal. Granting access to that wrong SID replaced
        the directory's entire DACL with one ACE nobody's running token
        actually held, making the directory unwritable even to the process
        that had just created it (confirmed live: `ensure_state_tree`
        failed on its very next line, writing `contacts.json`, and even
        `icacls`/`takeown` came back Access Denied afterwards - recovered
        only because the *owner* SID, set automatically at creation, still
        carried implicit WRITE_DAC). The token SID is always the one the
        current process can actually act as - see DECISIONS.md."""
        try:
            token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
            user, _attrs = win32security.GetTokenInformation(token, win32security.TokenUser)
            inherit_flags = ntsecuritycon.CONTAINER_INHERIT_ACE | ntsecuritycon.OBJECT_INHERIT_ACE
            dacl = win32security.ACL()
            dacl.AddAccessAllowedAceEx(
                win32security.ACL_REVISION, inherit_flags, ntsecuritycon.FILE_ALL_ACCESS, user
            )
            security_descriptor = win32security.GetFileSecurity(
                str(path), win32security.DACL_SECURITY_INFORMATION
            )
            security_descriptor.SetSecurityDescriptorDacl(1, dacl, 0)
            win32security.SetFileSecurity(
                str(path), win32security.DACL_SECURITY_INFORMATION, security_descriptor
            )
            return True
        except Exception:
            logger.warning("restrict_directory_to_current_user failed for %r", path, exc_info=True)
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
            "screenshot",
            "convert_docx_to_pdf",
            "restrict_directory_to_current_user",
        }
        return caps
