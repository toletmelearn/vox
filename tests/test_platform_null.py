"""With the adapter forced to NullAdapter, nothing may crash — every caller
must degrade via ToolResult(ok=False, ...) or a handled UnsupportedCapability
(spec Section 10 Phase 1 acceptance)."""
from __future__ import annotations

from pathlib import Path

import pytest

from vox.app import run_self_check
from vox.platform.base import UnsupportedCapability
from vox.tools.files import open_path


def test_open_path_degrades_gracefully_with_null_adapter(jail_settings, null_adapter):
    target = Path(jail_settings.paths.desktop, "notes.txt")
    target.write_text("hi", encoding="utf-8")

    result = open_path(path=str(target))
    assert result.ok is False


def test_null_adapter_raises_typed_exception_not_crash(null_adapter):
    from vox.platform import get_adapter

    with pytest.raises(UnsupportedCapability):
        get_adapter().list_windows()


def test_self_check_runs_without_crashing_on_null_adapter(jail_settings, null_adapter):
    run_self_check(jail_settings)
