"""Entrypoint. `python run.py --text "..."` drives the router without a mic;
`python run.py` with no args starts push-to-talk voice mode (spec Section
10, Phase 3)."""
from __future__ import annotations

import argparse
import sys
import threading

from vox.app import bootstrap, handle_text, start_voice_mode


def main() -> int:
    parser = argparse.ArgumentParser(prog="vox")
    parser.add_argument("--text", help="Send a text command through the router.")
    args = parser.parse_args()

    settings = bootstrap()

    if args.text:
        result = handle_text(args.text)
        print(result.speech)
        return 0 if result.ok else 1

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
