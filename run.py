"""Entrypoint. `python run.py --text "..."` drives the router without a mic
(spec Section 10, Phase 1). Voice input is wired in Phase 3."""
from __future__ import annotations

import argparse
import sys

from vox.app import bootstrap, handle_text


def main() -> int:
    parser = argparse.ArgumentParser(prog="vox")
    parser.add_argument("--text", help="Send a text command through the router.")
    args = parser.parse_args()

    bootstrap()

    if args.text:
        result = handle_text(args.text)
        print(result.speech)
        return 0 if result.ok else 1

    print("No input mode selected. Use --text \"...\" for now; voice lands in Phase 3.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
