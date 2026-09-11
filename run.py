"""Entrypoint. `python run.py --text "..."` drives the router without a mic
or a tray icon. `python run.py` with no args starts the full app: tray icon,
push-to-talk voice hotkey, and the text-hotkey command bar (spec Section 10,
Phase 5). `--no-tray` keeps Phase 3/4's headless voice-only loop, for a
machine with no display."""
from __future__ import annotations

import argparse
import sys
import threading

from vox.app import bootstrap, handle_text, start_voice_mode


def main() -> int:
    parser = argparse.ArgumentParser(prog="vox")
    parser.add_argument("--text", help="Send a text command through the router.")
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Headless voice-only mode, no tray icon or command bar (spec Phase 3/4 behaviour).",
    )
    args = parser.parse_args()

    settings = bootstrap()

    if args.text:
        result = handle_text(args.text)
        print(result.speech)
        return 0 if result.ok else 1

    if not args.no_tray:
        try:
            from vox.ui.tray import TrayApp
        except ImportError:
            print("Tray UI unavailable (see the log); falling back to --no-tray mode.")
        else:
            TrayApp(settings).run()  # blocks; Quit from the tray menu returns
            return 0

    capture = start_voice_mode(settings)
    if capture is None:
        print("Voice mode could not start (see the log). Use --text \"...\" instead.")
        return 1

    print(f"Hold {settings.hotkeys.voice} to talk. Ctrl+C to quit.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        capture.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
