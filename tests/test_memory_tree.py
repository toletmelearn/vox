"""memory/tree.py tests: the ~/.vox/ folder layout (spec Section 6C). Uses
null_adapter so restrict_directory_to_current_user raises UnsupportedCapability
- ensure_state_tree must swallow that and still create everything (invariant
9: degrade, never brick)."""
from __future__ import annotations

import json

from vox.memory.tree import append_transcript, archive_artifact, ensure_state_tree, prune_transcripts


def test_ensure_state_tree_creates_all_directories(tmp_path, null_adapter):
    state_dir = tmp_path / "vox-state"
    dirs = ensure_state_tree(state_dir)

    for d in dirs:
        assert d.is_dir()
    assert (state_dir / "memory").is_dir()
    assert (state_dir / "artifacts").is_dir()
    assert (state_dir / "cache" / "models").is_dir()
    assert (state_dir / "transcripts").is_dir()


def test_ensure_state_tree_creates_empty_json_files(tmp_path, null_adapter):
    state_dir = tmp_path / "vox-state"
    ensure_state_tree(state_dir)

    for name in ("contacts.json", "aliases.json", "preferences.json"):
        path = state_dir / "memory" / name
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_ensure_state_tree_does_not_overwrite_existing_files(tmp_path, null_adapter):
    state_dir = tmp_path / "vox-state"
    ensure_state_tree(state_dir)
    (state_dir / "memory" / "aliases.json").write_text(json.dumps({"yt": "youtube"}), encoding="utf-8")

    ensure_state_tree(state_dir)  # a second run must not clobber user edits

    assert json.loads((state_dir / "memory" / "aliases.json").read_text(encoding="utf-8")) == {"yt": "youtube"}


def test_ensure_state_tree_degrades_gracefully_when_acl_unsupported(tmp_path, null_adapter):
    # null_adapter raises UnsupportedCapability for restrict_directory_to_current_user;
    # this must not crash the whole tree-creation step (invariant 9).
    dirs = ensure_state_tree(tmp_path / "vox-state")
    assert len(dirs) == 5


def test_append_transcript_writes_one_jsonl_line_per_call(tmp_path):
    state_dir = tmp_path / "vox-state"
    append_transcript(state_dir, "make a folder called Test")
    append_transcript(state_dir, "what's the time")

    files = list((state_dir / "transcripts").glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["text"] == "make a folder called Test"


def test_prune_transcripts_removes_files_outside_retention(tmp_path):
    state_dir = tmp_path / "vox-state"
    transcripts_dir = state_dir / "transcripts"
    transcripts_dir.mkdir(parents=True)
    (transcripts_dir / "2020-01.jsonl").write_text("old", encoding="utf-8")
    (transcripts_dir / "2026-01.jsonl").write_text("recent", encoding="utf-8")

    from datetime import datetime

    removed = prune_transcripts(state_dir, retention_days=90, now=datetime(2026, 1, 15))

    assert removed == 1
    assert not (transcripts_dir / "2020-01.jsonl").exists()
    assert (transcripts_dir / "2026-01.jsonl").exists()


def test_prune_transcripts_on_missing_directory_is_a_noop(tmp_path):
    assert prune_transcripts(tmp_path / "vox-state", retention_days=90) == 0


def test_archive_artifact_hardlinks_into_dated_folder(tmp_path):
    state_dir = tmp_path / "vox-state"
    src = tmp_path / "Notes.docx"
    src.write_text("content", encoding="utf-8")

    archive_artifact(src, state_dir)

    from datetime import datetime

    dated_dir = state_dir / "artifacts" / datetime.now().strftime("%Y-%m-%d")
    assert (dated_dir / "Notes.docx").read_text(encoding="utf-8") == "content"


def test_archive_artifact_falls_back_to_copy_across_volumes(tmp_path, mocker):
    state_dir = tmp_path / "vox-state"
    src = tmp_path / "Notes.docx"
    src.write_text("content", encoding="utf-8")

    mocker.patch("vox.memory.tree.os.link", side_effect=OSError("cross-device link"))
    copy_mock = mocker.patch("vox.memory.tree.shutil.copy2", wraps=__import__("shutil").copy2)

    archive_artifact(src, state_dir)

    copy_mock.assert_called_once()
    from datetime import datetime

    dated_dir = state_dir / "artifacts" / datetime.now().strftime("%Y-%m-%d")
    assert (dated_dir / "Notes.docx").exists()


def test_archive_artifact_is_a_noop_if_already_archived(tmp_path, mocker):
    state_dir = tmp_path / "vox-state"
    src = tmp_path / "Notes.docx"
    src.write_text("content", encoding="utf-8")
    archive_artifact(src, state_dir)

    link_mock = mocker.patch("vox.memory.tree.os.link")
    archive_artifact(src, state_dir)  # second call: destination already exists

    link_mock.assert_not_called()
