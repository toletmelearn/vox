"""logging_setup.py: real, live finding - a tray mainloop crash logged via
pystray's own "pystray.*" logger left zero trace in vox.log, since that
logger is a sibling namespace to "vox", not a descendant of it, and
propagation only walks up dotted-name ancestry. Confirms the fix: the same
handlers are attached directly to the "pystray" logger too."""
from __future__ import annotations

import logging

from vox.config import Settings
from vox.logging_setup import setup_logging


def test_setup_logging_attaches_handlers_to_pystray_logger_too(tmp_path):
    settings = Settings()
    settings.logging.file = str(tmp_path / "vox.log")

    setup_logging(settings)

    vox_handlers = logging.getLogger("vox").handlers
    pystray_handlers = logging.getLogger("pystray").handlers
    assert len(pystray_handlers) == len(vox_handlers) == 2
    # the exact same handler instances, not separately-constructed copies -
    # one rotating log file, not two
    assert set(pystray_handlers) == set(vox_handlers)


def test_pystray_error_actually_lands_in_the_log_file(tmp_path):
    log_path = tmp_path / "vox.log"
    settings = Settings()
    settings.logging.file = str(log_path)

    setup_logging(settings)

    try:
        raise RuntimeError("simulated GetMessage failure")
    except RuntimeError:
        logging.getLogger("pystray._base").error(
            "An error occurred in the main loop", exc_info=True
        )

    contents = log_path.read_text(encoding="utf-8")
    assert "An error occurred in the main loop" in contents
    assert "RuntimeError: simulated GetMessage failure" in contents


def test_setup_logging_is_idempotent_no_duplicate_pystray_handlers(tmp_path):
    settings = Settings()
    settings.logging.file = str(tmp_path / "vox.log")

    setup_logging(settings)
    setup_logging(settings)

    assert len(logging.getLogger("pystray").handlers) == 2
