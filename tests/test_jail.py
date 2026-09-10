"""Path jail tests. Covers all six attack cases from spec Section 8.2 plus
the valid-path control case. Never touches the real Desktop (uses
jail_settings, which points every root at tmp_path)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vox.security.jail import JailViolation, resolve_in_jail


def test_relative_traversal_escapes_parent_is_rejected(jail_settings):
    with pytest.raises(JailViolation):
        resolve_in_jail("../../Windows/System32", parent_key="desktop")


def test_absolute_windows_path_outside_jail_is_rejected(jail_settings):
    with pytest.raises(JailViolation):
        resolve_in_jail("C:\\Windows\\System32")


def test_home_ssh_path_outside_jail_is_rejected(jail_settings):
    with pytest.raises(JailViolation):
        resolve_in_jail("~/.ssh")


@pytest.mark.skipif(sys.platform != "win32", reason="symlink test targets Windows paths")
def test_symlink_pointing_outside_jail_is_rejected(jail_settings, tmp_path: Path):
    outside = tmp_path.parent / "outside_target"
    outside.mkdir(exist_ok=True)
    desktop = Path(jail_settings.paths.desktop)
    link = desktop / "escape_link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("creating symlinks requires elevated privilege on this machine")

    with pytest.raises(JailViolation):
        resolve_in_jail("escape_link/evil.txt", parent_key="desktop")


def test_unc_path_is_rejected(jail_settings):
    with pytest.raises(JailViolation):
        resolve_in_jail("\\\\server\\share")


def test_valid_nested_path_is_accepted(jail_settings):
    resolved = resolve_in_jail("sub/notes.txt", parent_key="desktop")
    desktop = Path(jail_settings.paths.desktop).resolve()
    assert resolved == desktop / "sub" / "notes.txt"
    assert resolved.is_relative_to(desktop)


def test_unknown_parent_keyword_is_rejected(jail_settings):
    with pytest.raises(JailViolation):
        resolve_in_jail("evil", parent_key="system32")


def test_relative_path_without_parent_is_rejected(jail_settings):
    with pytest.raises(JailViolation):
        resolve_in_jail("relative/no/parent/given")
