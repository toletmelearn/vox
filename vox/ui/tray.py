"""System tray icon (spec Section 10 Phase 5): idle/listening/thinking/error
states, balloon notifications (spec 3A.1: pystray only, no WinRT toast), and
the menu that opens the command bar / settings / undo. Owns starting the
voice hotkey, the text hotkey, and the Esc kill-switch listener - the three
things that need to be alive for the whole session."""
from __future__ import annotations

import logging
import threading
from typing import Literal

import pystray
from PIL import Image, ImageDraw

from vox import app as vox_app
from vox.config import Settings
from vox.platform import get_adapter
from vox.security import confirm
from vox.tools.registry import ToolResult
from vox.ui.command_bar import CommandBar, CommandHistory
from vox.ui.hotkeys import AbortHotkeyListener, TapHotkeyListener
from vox.ui.settings import SettingsWindow

logger = logging.getLogger("vox.ui.tray")

TrayState = Literal["idle", "listening", "thinking", "error"]

# Real, live finding: pystray's own _win32.py::_mainloop() wraps the Win32
# GetMessage pump in a bare `except:` that logs and swallows any failure,
# then tears down its window and returns *normally* - so Icon.run()
# returning is not, on its own, evidence of a clean Quit. Without the
# retry loop in run() below, that silent return fell straight through to
# run.py's `return 0` -> `sys.exit(0)`, which - since every hotkey/voice
# thread here is a daemon thread (pynput's Listener sets daemon=True by
# design; HotkeyCapture's worker does too) - killed the voice hotkey, the
# text hotkey/command bar, and the kill switch along with the icon.
# Bounded, not infinite: a genuinely broken tray environment (not just one
# transient hiccup) shouldn't spin-restart forever.
_MAX_MAINLOOP_RESTARTS = 3

_STATE_COLORS: dict[str, tuple[int, int, int]] = {
    "idle": (120, 120, 120),
    "listening": (40, 180, 40),
    "thinking": (60, 120, 220),
    "error": (200, 40, 40),
}


def make_icon_image(state: str, size: int = 64) -> Image.Image:
    """Pure and display-independent - PIL draws in memory, no window needed
    - so this is unit tested directly."""
    color = _STATE_COLORS.get(state, _STATE_COLORS["idle"])
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 8
    draw.ellipse((margin, margin, size - margin, size - margin), fill=color)
    return image


class TrayApp:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._history = CommandHistory()
        self._voice_capture: vox_app.VoiceCapture | None = None
        self._text_listener: TapHotkeyListener | None = None
        self._abort_listener: AbortHotkeyListener | None = None
        self._quit_requested = False
        self._icon = pystray.Icon(
            "vox", icon=make_icon_image("idle"), title="vox - idle", menu=self._build_menu()
        )
        confirm.set_undo_listener(self._on_undo_armed)

    def set_state(self, state: TrayState) -> None:
        self._icon.icon = make_icon_image(state)
        self._icon.title = f"vox - {state}"

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Open command bar", lambda icon, item: self._open_command_bar()),
            pystray.MenuItem("Settings", lambda icon, item: self._open_settings()),
            pystray.MenuItem(
                "Undo last action",
                lambda icon, item: confirm.perform_undo(),
                enabled=lambda item: confirm.get_pending_undo() is not None,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda icon, item: self._quit()),
        )

    def _on_undo_armed(self, pending: confirm.PendingUndo) -> None:
        try:
            self._icon.notify(
                f"{pending.tool} - undo available for {int(pending.window_s)}s from the tray menu",
                "vox",
            )
        except Exception:
            logger.debug("tray notify failed", exc_info=True)

    def _run_text_command(self, text: str) -> ToolResult:
        self.set_state("thinking")
        return vox_app.handle_text(text)

    def _speak_and_settle(self, result: ToolResult) -> None:
        try:
            from vox.audio.tts import speak

            speak(result.speech)
        except Exception:
            logger.warning("speak failed for command bar result", exc_info=True)
        self.set_state("idle")

    def _open_command_bar(self) -> None:
        try:
            CommandBar(
                submit=self._run_text_command,
                on_result=self._speak_and_settle,
                history=self._history,
            ).show()
        except Exception:
            logger.error("command bar raised", exc_info=True)
            self.set_state("error")

    def _open_settings(self) -> None:
        try:
            SettingsWindow(
                self._settings,
                verify_available=get_adapter().verify_hotkey_available,
                swap_voice_listener=self._swap_voice_listener,
                swap_text_listener=self._swap_text_listener,
            ).show()
        except Exception:
            logger.error("settings window raised", exc_info=True)

    def _swap_voice_listener(self, chord: str) -> bool:
        """Unregisters the current voice hotkey and registers `chord`
        instead, with no restart (spec Section 6E). Rolls the in-memory
        chord back to its previous value on failure so a caller retrying
        with the old chord (apply_hotkey_change's rollback) really does
        restore the working listener."""
        if self._voice_capture is not None:
            self._voice_capture.stop()
            self._voice_capture = None
        previous = self._settings.hotkeys.voice
        self._settings.hotkeys.voice = chord
        capture = vox_app.start_voice_mode(self._settings, on_state_change=self.set_state)
        if capture is None:
            self._settings.hotkeys.voice = previous
            return False
        self._voice_capture = capture
        return True

    def _swap_text_listener(self, chord: str) -> bool:
        if self._text_listener is not None:
            self._text_listener.stop()
            self._text_listener = None
        try:
            listener = TapHotkeyListener(chord, on_trigger=self._open_command_bar)
            listener.start()
        except Exception:
            logger.warning("could not register text hotkey %r", chord, exc_info=True)
            return False
        self._text_listener = listener
        return True

    def _quit(self) -> None:
        self._quit_requested = True
        if self._voice_capture is not None:
            self._voice_capture.stop()
        if self._text_listener is not None:
            self._text_listener.stop()
        if self._abort_listener is not None:
            self._abort_listener.stop()
        self._icon.stop()

    def _on_ready(self, icon: pystray.Icon) -> None:
        icon.visible = True
        self._voice_capture = vox_app.start_voice_mode(self._settings, on_state_change=self.set_state)
        self._swap_text_listener(self._settings.hotkeys.text)
        self._abort_listener = AbortHotkeyListener(on_trigger=confirm.get_kill_switch().trigger)
        self._abort_listener.start()
        logger.info(
            "Tray ready. Voice: %s (%s). Text: %s.",
            self._settings.hotkeys.voice,
            "listening" if self._voice_capture is not None else "unavailable - use the command bar",
            self._settings.hotkeys.text,
        )

    def _on_restart(self, icon: pystray.Icon) -> None:
        """Setup callback for a re-created icon after a mainloop crash - the
        voice/text/abort listeners _on_ready started are still alive (they
        run on their own daemon threads, independent of the tray's own
        message loop), so this must not start a second copy of any of
        them, just make the replacement icon visible."""
        icon.visible = True
        logger.info("Tray icon restarted; voice/text hotkeys were not affected.")

    def run(self) -> None:
        """Blocks the calling thread - pystray owns the native message loop
        on it. Call this from the main thread only.

        See the _MAX_MAINLOOP_RESTARTS comment above: Icon.run() returning
        does not by itself mean the user chose Quit, so `_quit_requested`
        (set only by `_quit()`) is the actual signal checked here. A crash
        recreates the icon and keeps going; exhausting the retry budget
        degrades to a headless wait (invariant 9: degrade, never brick) -
        the voice/text hotkeys and kill switch keep running with no tray
        icon at all, rather than the whole process silently exiting."""
        attempts = 0
        while attempts <= _MAX_MAINLOOP_RESTARTS:
            self._quit_requested = False
            try:
                self._icon.run(setup=self._on_ready if attempts == 0 else self._on_restart)
            except Exception:
                logger.error("Tray icon's run() raised unexpectedly.", exc_info=True)

            if self._quit_requested:
                return

            attempts += 1
            if attempts > _MAX_MAINLOOP_RESTARTS:
                break
            logger.error(
                "Tray icon's message loop ended without a Quit request "
                "(restart %d/%d) - recreating the icon.",
                attempts,
                _MAX_MAINLOOP_RESTARTS,
            )
            self._icon = pystray.Icon(
                "vox", icon=make_icon_image("idle"), title="vox - idle", menu=self._build_menu()
            )

        logger.error(
            "Tray icon's message loop failed %d times in a row; giving up "
            "on the icon for this session. Voice (%s) and text (%s) "
            "hotkeys keep running - press Ctrl+C in this console, or "
            "restart vox, to quit.",
            _MAX_MAINLOOP_RESTARTS,
            self._settings.hotkeys.voice,
            self._settings.hotkeys.text,
        )
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            self._quit()
