"""Spotlight/Alfred-style command bar (spec Section 6D): text is a first-class
input path, not a debug fallback. Opens on the text hotkey, submits to the
same router as voice, produces an identical audit row apart from
`source="text"` (source is recorded implicitly - `execute_tool_call`'s
`tier` field is the same for both; the only difference is `stt_confidence`,
fixed at 1.0 for text same as any other typed command).

`CommandHistory` and `compute_hint` are plain Python, tested without a
display. `CommandBar` is the thin Tkinter shell over them - it is not unit
tested directly (spec Section 13 tests never require a display); the app
wires it up so a real user can drive it interactively."""
from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable

from vox.platform import get_adapter
from vox.platform.base import UnsupportedCapability
from vox.router import tier0_grammar
from vox.tools.registry import ToolResult

logger = logging.getLogger("vox.ui.command_bar")

MAX_HISTORY = 5
BAR_WIDTH_PX = 600


class CommandHistory:
    """Last MAX_HISTORY submitted commands, newest last. Up/Down cursor
    walks backwards/forwards through it without mutating the underlying
    list until a new command is actually submitted."""

    def __init__(self, max_size: int = MAX_HISTORY) -> None:
        self._max_size = max_size
        self._items: list[str] = []
        self._cursor: int | None = None

    def add(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._items.append(text)
        if len(self._items) > self._max_size:
            self._items = self._items[-self._max_size :]
        self._cursor = None

    def older(self) -> str | None:
        if not self._items:
            return None
        if self._cursor is None:
            self._cursor = len(self._items) - 1
        elif self._cursor > 0:
            self._cursor -= 1
        return self._items[self._cursor]

    def newer(self) -> str | None:
        if self._cursor is None:
            return None
        if self._cursor < len(self._items) - 1:
            self._cursor += 1
            return self._items[self._cursor]
        self._cursor = None
        return ""

    def reset_cursor(self) -> None:
        self._cursor = None


def compute_hint(text: str) -> str:
    """Live inline hint: which tool Tier 0 would match right now, if any.
    Never executes anything - tier0_grammar.route() only builds a ToolCall,
    it doesn't call the tool (spec Section 6D: 'teaches the grammar faster
    than any documentation')."""
    if not text.strip():
        return ""
    result = tier0_grammar.route(text)
    if result.call is not None:
        return f"-> {result.call.name}"
    if result.clarification is not None:
        return f"-> (needs more info: {result.clarification})"
    return "(no Tier 0 match - will try the local model)"


class CommandBar:
    """One-shot Tkinter window: build, show, get one command, close. A fresh
    Tk() root per open rather than a persistent hidden root, matching
    security/confirm.py's dialog and avoiding any shared-mainloop lifecycle
    with the tray icon's own event loop."""

    def __init__(
        self,
        submit: Callable[[str], ToolResult],
        on_result: Callable[[ToolResult], None] | None = None,
        history: CommandHistory | None = None,
    ) -> None:
        self._submit = submit
        self._on_result = on_result
        self._history = history if history is not None else CommandHistory()

    def _close_without_acting(self, root: tk.Tk) -> None:
        self._history.reset_cursor()
        root.destroy()

    def _on_submit(self, root: tk.Tk, entry: tk.Entry) -> None:
        text = entry.get()
        root.destroy()
        if not text.strip():
            return
        self._history.add(text)
        result = self._submit(text)
        logger.info("command bar: %r -> ok=%s speech=%r", text, result.ok, result.speech)
        if self._on_result is not None:
            try:
                self._on_result(result)
            except Exception:
                logger.warning("command bar on_result raised", exc_info=True)

    def show(self) -> None:
        root = tk.Tk()
        root.title("vox")
        root.attributes("-topmost", True)
        # Never steals focus without the hotkey (spec Section 6D) - this
        # window only exists because the hotkey was just pressed to create it.
        root.overrideredirect(True)

        frame = tk.Frame(root, padx=10, pady=8)
        frame.pack(fill="both", expand=True)

        entry = tk.Entry(frame, width=60, font=("Segoe UI", 13))
        entry.pack(fill="x")
        entry.focus_set()

        hint = tk.Label(frame, text="", anchor="w", fg="#888888", font=("Segoe UI", 9))
        hint.pack(fill="x", pady=(4, 0))

        def _on_key_release(_event: object) -> None:
            hint.config(text=compute_hint(entry.get()))

        def _history_older(_event: object) -> str:
            older = self._history.older()
            if older is not None:
                entry.delete(0, tk.END)
                entry.insert(0, older)
            return "break"

        def _history_newer(_event: object) -> str:
            newer = self._history.newer()
            if newer is not None:
                entry.delete(0, tk.END)
                entry.insert(0, newer)
            return "break"

        entry.bind("<KeyRelease>", _on_key_release)
        entry.bind("<Up>", _history_older)
        entry.bind("<Down>", _history_newer)
        entry.bind("<Return>", lambda _e: self._on_submit(root, entry))
        entry.bind("<Escape>", lambda _e: self._close_without_acting(root))
        root.protocol("WM_DELETE_WINDOW", lambda: self._close_without_acting(root))

        root.update_idletasks()
        w = BAR_WIDTH_PX
        h = root.winfo_reqheight()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{sh // 4}")

        # Tk's own focus_set()/focus_force() only ever set Tk-internal
        # keyboard focus - they don't call SetForegroundWindow, so Windows
        # can silently deny real OS input focus to a window created on a
        # background thread (this listener fires from the hotkey's own
        # thread, not the main thread). Force an actual paint with update()
        # first so the window genuinely exists on screen before asking the
        # OS to foreground it, then let the platform adapter do the
        # OS-specific part (CLAUDE.md invariant 4) - the same
        # SetForegroundWindow call the "focus window" voice tool already
        # uses, which on Windows also works around the foreground-lock
        # timeout that made this flaky (see platform/windows.py).
        root.update()
        root.lift()
        root.focus_force()
        entry.focus_set()
        try:
            get_adapter().focus_window(root.winfo_id())
        except UnsupportedCapability:
            pass
        except Exception:
            logger.debug("could not force OS-level foreground focus", exc_info=True)

        root.mainloop()
