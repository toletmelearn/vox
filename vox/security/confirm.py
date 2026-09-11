"""Risk-tier guard rails (spec Section 8.4, Section 8.7): the destructive-risk
confirmation modal, the medium-risk undo window, and the global kill switch.
All three are UI-agnostic here — vox/ui/ only supplies the tray toast and
reads pending-undo state; nothing in this module imports vox.ui, so app.py
and the tools layer never depend on a display existing."""
from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import send2trash

logger = logging.getLogger("vox.security.confirm")

ConfirmHandler = Callable[[str, dict[str, Any]], bool]


def _tk_confirm_dialog(tool_name: str, args: dict[str, Any]) -> bool:
    """Real modal: shows the tool name and resolved arguments, Cancel is the
    default and focused button (spec Section 10 Phase 5 acceptance)."""
    result = {"confirmed": False}

    root = tk.Tk()
    root.title("vox - confirm action")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    tk.Label(root, text=f"Run {tool_name!r}?", font=("Segoe UI", 11, "bold")).pack(
        padx=16, pady=(16, 4)
    )
    detail = "\n".join(f"{k} = {v!r}" for k, v in args.items()) or "(no arguments)"
    tk.Label(root, text=detail, justify="left", font=("Consolas", 9)).pack(padx=16, pady=4)

    def _confirm() -> None:
        result["confirmed"] = True
        root.destroy()

    def _cancel() -> None:
        result["confirmed"] = False
        root.destroy()

    buttons = tk.Frame(root)
    buttons.pack(pady=(8, 16))
    cancel_btn = tk.Button(buttons, text="Cancel", width=10, command=_cancel)
    cancel_btn.pack(side="left", padx=6)
    tk.Button(buttons, text="Confirm", width=10, command=_confirm).pack(side="left", padx=6)

    root.protocol("WM_DELETE_WINDOW", _cancel)  # closing the window = cancel
    cancel_btn.focus_set()
    root.bind("<Return>", lambda _e: _cancel())  # Enter activates the default (Cancel)
    root.bind("<Escape>", lambda _e: _cancel())

    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    root.mainloop()
    return result["confirmed"]


_handler: ConfirmHandler | None = None


def set_confirm_handler(handler: ConfirmHandler | None) -> None:
    """Test/headless hook: replace the real Tkinter dialog. Passing None
    restores the default."""
    global _handler
    _handler = handler


def reset_confirm_handler() -> None:
    global _handler
    _handler = None


def confirm_destructive(tool_name: str, args: dict[str, Any]) -> bool:
    """Block on confirmation for a destructive-risk tool call. Never
    auto-confirms (spec Section 8.4)."""
    handler = _handler or _tk_confirm_dialog
    return handler(tool_name, args)


class KillSwitch:
    """Esc anywhere aborts the in-flight action and stops TTS (spec Section
    8.7). A plain threading.Event, checked by long-running tools' loops."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def trigger(self) -> None:
        logger.info("Kill switch triggered; aborting in-flight work.")
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    def clear(self) -> None:
        self._event.clear()


_kill_switch = KillSwitch()


def get_kill_switch() -> KillSwitch:
    """Process-wide kill switch. A fresh command clears it at the start of
    routing (vox.app.route_and_execute) so an earlier abort can't leak into
    the next command."""
    return _kill_switch


@dataclass(frozen=True)
class PendingUndo:
    tool: str
    artifact_path: str
    armed_at: float
    window_s: float

    def expired(self, *, now: float | None = None) -> bool:
        return (now if now is not None else time.monotonic()) > self.armed_at + self.window_s


UndoListener = Callable[[PendingUndo], None]

_pending_undo: PendingUndo | None = None
_undo_listener: UndoListener | None = None
_undo_lock = threading.Lock()


def set_undo_listener(listener: UndoListener | None) -> None:
    """UI hook: vox/ui/tray.py registers here to pop a toast the instant an
    undo window opens. Optional - nothing else in the app depends on it."""
    global _undo_listener
    _undo_listener = listener


def arm_undo(tool: str, artifact_path: str, window_s: float) -> None:
    """Called after a medium-risk tool succeeds and produced an artifact
    (spec Section 8.4: 'a 4-second undo window where undo is possible - file
    creation, download')."""
    global _pending_undo
    pending = PendingUndo(
        tool=tool, artifact_path=artifact_path, armed_at=time.monotonic(), window_s=window_s
    )
    with _undo_lock:
        _pending_undo = pending
    if _undo_listener is not None:
        try:
            _undo_listener(pending)
        except Exception:
            logger.warning("undo listener raised", exc_info=True)


def get_pending_undo() -> PendingUndo | None:
    """Returns the armed undo, or None if nothing is armed or the window has
    already passed."""
    with _undo_lock:
        pending = _pending_undo
    if pending is None or pending.expired():
        return None
    return pending


def perform_undo() -> bool:
    """Sends the pending artifact to the recycle bin. Returns False if the
    window already closed or nothing is armed."""
    global _pending_undo
    pending = get_pending_undo()
    if pending is None:
        return False
    with _undo_lock:
        _pending_undo = None
    try:
        send2trash.send2trash(pending.artifact_path)
    except OSError:
        logger.warning("undo failed for %r", pending.artifact_path, exc_info=True)
        return False
    return True


def reset_undo_state() -> None:
    """Test teardown hook."""
    global _pending_undo, _undo_listener
    with _undo_lock:
        _pending_undo = None
    _undo_listener = None
