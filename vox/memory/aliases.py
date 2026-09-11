"""User-editable JSON stores (spec Section 6C): contacts, folder/app
shortcuts, and learned preferences. `memory/tree.py::ensure_state_tree`
creates these files empty on first run; this module is the load/get/set/save
layer over them. Phase 7's target resolver and messaging tools are the
first real consumers of `aliases`/`contacts` - this phase only builds the
storage layer itself, since nothing yet needs to read from it."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("vox.memory.aliases")


class JsonStore:
    """A single user-editable JSON file, loaded once and re-saved on
    write. If the user hand-edits it into invalid JSON, treat it as empty
    rather than crashing the app (invariant 9: degrade, never brick) - it's
    aliases, not the security core."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            loaded = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("could not read %r; treating as empty", self._path, exc_info=True)
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self.save()

    def all(self) -> dict[str, Any]:
        return dict(self._data)

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")


class AliasStore:
    """Bundles the three files spec Section 6C lists under `memory/`."""

    def __init__(self, state_dir: Path) -> None:
        self.contacts = JsonStore(state_dir / "memory" / "contacts.json")
        self.aliases = JsonStore(state_dir / "memory" / "aliases.json")
        self.preferences = JsonStore(state_dir / "memory" / "preferences.json")


_store: AliasStore | None = None


def get_alias_store() -> AliasStore:
    global _store
    if _store is None:
        from vox.config import get_settings

        state_dir = Path(get_settings().paths.state_dir).expanduser()
        _store = AliasStore(state_dir)
    return _store


def set_alias_store(store: AliasStore) -> None:
    """Test hook."""
    global _store
    _store = store


def reset_alias_store() -> None:
    global _store
    _store = None
