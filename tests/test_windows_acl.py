"""restrict_directory_to_current_user tests: real pywin32 ACL calls against
a disposable tmp_path (safe - unlike the real ~/.vox/ tree, tmp_path is
deleted after the test session). This is a regression suite for a real
incident (see DECISIONS.md): an earlier implementation resolved the current
user's SID via `LookupAccountName(GetUserName())`, which on at least one
real environment this project was tested on returned the machine/domain SID
with the final user RID missing - a *different*, unprivileged principal.
Granting access to that wrong SID replaced the directory's entire DACL,
leaving it unwritable even to the process that had just created it."""
from __future__ import annotations

from vox.platform.windows import WindowsAdapter


def test_restrict_directory_grants_the_current_process_write_access(tmp_path):
    target = tmp_path / "state"
    target.mkdir()

    adapter = WindowsAdapter()
    assert adapter.restrict_directory_to_current_user(target) is True

    probe = target / "probe.txt"
    probe.write_text("hi", encoding="utf-8")  # must not raise PermissionError
    assert probe.read_text(encoding="utf-8") == "hi"


def test_restrict_directory_grants_write_access_to_new_child_files_afterwards(tmp_path):
    """The exact failure mode from the real incident: ensure_state_tree
    locks a directory down, then immediately writes a file inside it."""
    target = tmp_path / "state" / "memory"
    target.mkdir(parents=True)

    adapter = WindowsAdapter()
    adapter.restrict_directory_to_current_user(target)

    child = target / "contacts.json"
    child.write_text("{}", encoding="utf-8")
    assert child.exists()


def test_restrict_directory_applies_to_a_second_directory_independently(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    adapter = WindowsAdapter()
    assert adapter.restrict_directory_to_current_user(a) is True
    assert adapter.restrict_directory_to_current_user(b) is True

    (a / "x.txt").write_text("x", encoding="utf-8")
    (b / "y.txt").write_text("y", encoding="utf-8")
