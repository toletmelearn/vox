"""Path allowlist resolution. Every filesystem path a tool touches must come
from resolve_in_jail() — see CLAUDE.md invariant 2 and spec Section 8.2.

`parent` is a closed keyword set (invariant 3): the LLM never authors an
absolute path, only one of these four literals."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from vox.config import get_settings

PARENT_KEYS = ("desktop", "documents", "downloads", "workdir")

# Same four values as PARENT_KEYS, as a type - tools import this for their
# `parent` parameter so its JSON schema (what Tier 1 actually sees) carries
# an explicit enum instead of an opaque `str`. Keep in sync with PARENT_KEYS
# by hand; a mismatch would only ever narrow what the type-checker accepts,
# never widen what resolve_in_jail() enforces at runtime.
ParentKey = Literal["desktop", "documents", "downloads", "workdir"]

_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {
    f"LPT{i}" for i in range(1, 10)
}
_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')
_CONTROL_CHARS = re.compile(r"[\x00-\x1f]")


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Strip characters that are illegal or dangerous in a filename (spec
    Section 8.3). Never accepts a name that could escape the jail via path
    separators or a reserved device name."""
    cleaned = _ILLEGAL_CHARS.sub("", name)
    cleaned = _CONTROL_CHARS.sub("", cleaned)
    cleaned = cleaned.strip(". ")
    cleaned = cleaned[:max_length]
    if not cleaned:
        raise JailViolation(f"filename sanitises to empty: {name!r}")
    stem = cleaned.split(".")[0].upper()
    if stem in _RESERVED_NAMES:
        raise JailViolation(f"reserved device name: {name!r}")
    return cleaned


class JailViolation(Exception):
    """Raised when a path resolves outside the configured jail roots. This is
    the one exception tools are allowed to let propagate (spec Section 12) so
    the guard layer can record a 'rejected' audit row."""


def jail_roots() -> list[Path]:
    """The four PARENT_KEYS roots, plus whatever extra roots
    `security.jail_roots` names. Deriving the four from `_parent_root`
    (rather than a second, separately-configured copy of the same four
    paths) is deliberate: a duplicate list is exactly how `paths.desktop`
    and the old `security.jail_roots` default drifted apart on a
    OneDrive-redirected machine, making a real, correctly-created folder
    on the real Desktop fail as "escaping the jail" - see DECISIONS.md.

    Deduplicated by resolved path: a config.yaml still carrying the old
    literal ~/Desktop-style entries in `security.jail_roots` (leftover from
    before that field was narrowed to "extra roots only") would otherwise
    list the same physical folder twice - once derived, once from config -
    which is confusing at best in the self-check table and, on a platform
    where two differently-spelled paths resolve to the same directory,
    could make an allowlist walk do redundant work. `dict.fromkeys`
    preserves first-seen order, so the derived PARENT_KEYS roots always
    win the display slot over a redundant config entry."""
    settings = get_settings()
    roots = [_parent_root(key) for key in PARENT_KEYS]
    roots += [Path(root).expanduser().resolve() for root in settings.security.jail_roots]
    return list(dict.fromkeys(roots))


def _parent_root(parent_key: str) -> Path:
    if parent_key not in PARENT_KEYS:
        raise JailViolation(f"unknown parent keyword: {parent_key!r}")
    settings = get_settings()
    raw = getattr(settings.paths, parent_key)
    return Path(raw).expanduser().resolve()


def _is_within(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def resolve_in_jail(user_path: str, parent_key: str | None = None) -> Path:
    """Resolve a user- or LLM-supplied path fragment to an absolute path,
    guaranteed to sit inside one of the configured jail roots.

    - With `parent_key`: `user_path` is a relative fragment under that named
      root (e.g. a folder/file name for create_folder).
    - Without: `user_path` must already be an absolute path (e.g. open_path
      on a path found by find_files); a bare relative path is rejected as
      ambiguous rather than resolved against the process CWD.
    """
    roots = jail_roots()

    if parent_key is not None:
        base = _parent_root(parent_key)
        raw = base / user_path
    else:
        raw = Path(user_path).expanduser()
        if not raw.is_absolute():
            raise JailViolation(
                f"relative path given without a parent keyword: {user_path!r}"
            )

    try:
        candidate = raw.resolve(strict=False)
    except OSError as exc:
        # A UNC path to an unreachable host can make Path.resolve() attempt
        # live network resolution and raise, instead of just normalising
        # the string (observed with \\server\share on Windows). Any path we
        # can't safely resolve is rejected, not silently let through.
        raise JailViolation(f"could not resolve path: {user_path!r} ({exc})") from exc

    if not _is_within(candidate, roots):
        raise JailViolation(f"path escapes the jail: {user_path!r} -> {candidate}")

    return candidate
