"""Factory returning the PlatformAdapter for the running OS. This is the one
place allowed to inspect sys.platform (invariant 4) — every other module asks
the adapter for a capability instead."""
from __future__ import annotations

import logging
import sys

from vox.platform.base import PlatformAdapter
from vox.platform.null import NullAdapter

logger = logging.getLogger("vox.platform")

_adapter: PlatformAdapter | None = None


def _create_adapter() -> PlatformAdapter:
    if sys.platform == "win32":
        from vox.platform.windows import WindowsAdapter

        return WindowsAdapter()
    if sys.platform.startswith("linux"):
        from vox.platform.linux import LinuxAdapter

        return LinuxAdapter()
    logger.warning("Unsupported platform %r, falling back to NullAdapter", sys.platform)
    return NullAdapter()


def get_adapter() -> PlatformAdapter:
    global _adapter
    if _adapter is None:
        _adapter = _create_adapter()
    return _adapter


def set_adapter(adapter: PlatformAdapter) -> None:
    """Test hook, and the escape valve to force NullAdapter for the
    'nothing crashes with no capabilities' acceptance run."""
    global _adapter
    _adapter = adapter


def reset_adapter() -> None:
    """Test teardown hook: forget the cached adapter so the next get_adapter()
    call re-detects the real platform."""
    global _adapter
    _adapter = None
