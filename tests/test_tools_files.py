"""Tool tests use tmp_path via jail_settings; never touch the real Desktop
(spec Section 13)."""
from __future__ import annotations

from pathlib import Path

from vox.security.jail import JailViolation
from vox.tools.files import (
    create_folder,
    create_text_file,
    find_files,
    move_to_trash,
    open_path,
)


def test_create_folder_creates_directory(jail_settings):
    result = create_folder(name="Physics Notes", parent="desktop")
    assert result.ok
    assert Path(jail_settings.paths.desktop, "Physics Notes").is_dir()


def test_create_folder_rejects_traversal(jail_settings):
    import pytest

    with pytest.raises(JailViolation):
        create_folder(name="../../evil", parent="desktop")
    assert not (Path(jail_settings.paths.desktop).parent.parent / "evil").exists()


def test_create_folder_existing_fails_gracefully(jail_settings):
    create_folder(name="dup", parent="desktop")
    result = create_folder(name="dup", parent="desktop")
    assert not result.ok


def test_create_text_file_appends_txt_extension(jail_settings):
    result = create_text_file(name="todo", content="buy milk", parent="desktop")
    assert result.ok
    path = Path(jail_settings.paths.desktop, "todo.txt")
    assert path.read_text(encoding="utf-8") == "buy milk"


def test_open_path_missing_file_fails_gracefully(jail_settings):
    result = open_path(path=str(Path(jail_settings.paths.desktop, "nope.txt")))
    assert not result.ok


def test_find_files_matches_by_fragment(jail_settings):
    create_text_file(name="quarterly-report", parent="desktop")
    result = find_files(query="report")
    assert result.ok
    assert "quarterly-report.txt" in result.detail


def test_move_to_trash_missing_file_fails_gracefully(jail_settings):
    result = move_to_trash(path=str(Path(jail_settings.paths.desktop, "nope.txt")))
    assert not result.ok
