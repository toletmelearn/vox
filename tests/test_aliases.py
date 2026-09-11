"""memory/aliases.py tests: the user-editable JSON stores (spec Section 6C).
Phase 7 is the first real consumer; this phase only builds the storage
layer, so these tests cover load/get/set/persist and the degrade-on-bad-
JSON path."""
from __future__ import annotations

import json

from vox.memory.aliases import AliasStore, JsonStore


def test_json_store_missing_file_is_empty(tmp_path):
    store = JsonStore(tmp_path / "aliases.json")
    assert store.all() == {}
    assert store.get("yt") is None
    assert store.get("yt", "default") == "default"


def test_json_store_set_persists_to_disk(tmp_path):
    path = tmp_path / "aliases.json"
    store = JsonStore(path)
    store.set("yt", "youtube")

    assert json.loads(path.read_text(encoding="utf-8")) == {"yt": "youtube"}

    reloaded = JsonStore(path)
    assert reloaded.get("yt") == "youtube"


def test_json_store_delete(tmp_path):
    store = JsonStore(tmp_path / "aliases.json")
    store.set("yt", "youtube")
    store.delete("yt")
    assert store.get("yt") is None


def test_json_store_degrades_on_invalid_json(tmp_path):
    path = tmp_path / "aliases.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = JsonStore(path)
    assert store.all() == {}


def test_json_store_degrades_on_non_object_json(tmp_path):
    path = tmp_path / "aliases.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    store = JsonStore(path)
    assert store.all() == {}


def test_alias_store_bundles_three_files(tmp_path):
    store = AliasStore(tmp_path)
    store.contacts.set("Subodh", {"whatsapp": "+91..."})
    store.aliases.set("yt", "youtube")
    store.preferences.set("preferred_browser", "chrome")

    assert (tmp_path / "memory" / "contacts.json").exists()
    assert (tmp_path / "memory" / "aliases.json").exists()
    assert (tmp_path / "memory" / "preferences.json").exists()
