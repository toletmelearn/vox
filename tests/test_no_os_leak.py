"""Automated form of the Phase 1 grep gate (CLAUDE.md invariant 4): no
sys.platform / platform.system / os.name literal outside vox/platform/."""
from __future__ import annotations

import re
from pathlib import Path

_PATTERN = re.compile(r"sys\.platform|platform\.system|os\.name")
_VOX_ROOT = Path(__file__).resolve().parent.parent / "vox"


def test_no_os_specific_checks_outside_platform_package():
    leaks = []
    for path in _VOX_ROOT.rglob("*.py"):
        if _VOX_ROOT / "platform" in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _PATTERN.search(line):
                leaks.append(f"{path}:{lineno}: {line.strip()}")
    assert not leaks, "OS-specific checks leaked outside vox/platform/:\n" + "\n".join(leaks)
