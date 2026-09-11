"""Short-term context (spec Section 6C): held in process, what makes
follow-up commands like 'make that a PDF' work. A process-wide singleton,
same DI pattern as security/audit.py's get_audit_log()."""
from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Artifact:
    path: str
    kind: str
    title: str


@dataclass(frozen=True)
class Turn:
    transcript: str
    tool: str | None
    speech: str


class Context:
    """`last_artifact`/`last_target`/`last_folder` are set by the guard
    layer (app.py) after a successful execution; `recent_turns` after every
    routed command, successful or not. Expiry is checked against
    `time.monotonic()` at the moment each value was set, not wall-clock
    time, so it's immune to system clock adjustments - tests advance it by
    mocking `time.monotonic` (see tests/test_context.py)."""

    def __init__(self, session_id: str | None = None, *, recent_turns_max: int = 6) -> None:
        self.session_id = session_id or uuid.uuid4().hex
        self.last_artifact: Artifact | None = None
        self.last_target: str | None = None
        self.last_folder: str | None = None
        self.recent_turns: deque[Turn] = deque(maxlen=recent_turns_max)
        self._last_activity_at = time.monotonic()

    def touch(self) -> None:
        self._last_activity_at = time.monotonic()

    def is_expired(self, ttl_minutes: float) -> bool:
        return (time.monotonic() - self._last_activity_at) > (ttl_minutes * 60)

    def start_new_session(self) -> None:
        self.session_id = uuid.uuid4().hex
        self.last_artifact = None
        self.last_target = None
        self.last_folder = None
        self.recent_turns.clear()
        self.touch()

    def set_last_artifact(self, path: str, kind: str, title: str) -> None:
        self.last_artifact = Artifact(path=path, kind=kind, title=title)
        self.touch()

    def add_turn(self, transcript: str, tool: str | None, speech: str) -> None:
        self.recent_turns.append(Turn(transcript=transcript, tool=tool, speech=speech))
        self.touch()


_context: Context | None = None


def get_context() -> Context:
    global _context
    if _context is None:
        _context = Context()
    return _context


def set_context(context: Context) -> None:
    """Test hook."""
    global _context
    _context = context


def reset_context() -> None:
    global _context
    _context = None
