"""Rotating file logger + console handler. Must be called once at startup."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from vox.config import Settings


def setup_logging(settings: Settings) -> logging.Logger:
    logger = logging.getLogger("vox")
    logger.setLevel(settings.logging.level)
    logger.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(console)

    log_path = Path(settings.logging.file).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)

    # pystray logs its own internal failures (e.g. the Win32 message-loop
    # crash ui/tray.py's run() wraps) through a "pystray.*" logger — a
    # sibling namespace to "vox", not a descendant of it. Propagation only
    # walks up dotted-name ancestry, so those records would otherwise never
    # reach the handlers above and fall through to Python's stderr-only
    # "handler of last resort" — visible in whatever terminal happens to be
    # attached, never written to vox.log. Confirmed live: a real tray
    # mainloop crash left zero trace in vox.log until this was added. See
    # DECISIONS.md.
    pystray_logger = logging.getLogger("pystray")
    pystray_logger.setLevel(settings.logging.level)
    pystray_logger.handlers.clear()
    pystray_logger.addHandler(console)
    pystray_logger.addHandler(file_handler)

    return logger
