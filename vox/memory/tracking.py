"""Artifact/activity tracking hook for the guard layer (spec Section 6C:
"The guard layer, after a successful execution, writes an artifacts row").
Split out of app.py's execute_tool_call to keep that module under
CLAUDE.md's 300-line guideline - app.py still calls this, once, after a
tool call's outcome is known; the guard layer's actual identity (writing
the audit row, running the confirm gate) stays in app.py."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from vox.config import get_settings
from vox.memory.context import get_context
from vox.memory.store import artifact_kind, get_memory_store
from vox.memory.tree import append_transcript, archive_artifact
from vox.router.base import ToolCall
from vox.tools.registry import ToolResult

Outcome = Literal["ok", "failed", "cancelled"]


def record_execution(call: ToolCall, *, transcript: str, outcome: Outcome, result: ToolResult) -> None:
    settings = get_settings()
    context = get_context()
    store = get_memory_store()
    state_dir = Path(settings.paths.state_dir).expanduser()

    if settings.memory.store_transcripts:
        stored_transcript = transcript
        append_transcript(state_dir, transcript)
    else:
        # spec Section 6C: "when false, activity.transcript stores the
        # matched tool name only, not the spoken text" - and per the Phase
        # 6 acceptance criterion, nothing spoken is written to disk at all,
        # so append_transcript is not called in this branch.
        stored_transcript = call.name

    artifact_id = None
    if outcome == "ok" and result.artifact_path:
        kind = artifact_kind(call.name, result.artifact_path)
        title = Path(result.artifact_path).name
        artifact_id = store.record_artifact(
            path=result.artifact_path, kind=kind, title=title, source_transcript=stored_transcript
        )
        context.set_last_artifact(result.artifact_path, kind, title)
        if settings.memory.keep_artifact_copies:
            archive_artifact(Path(result.artifact_path), state_dir)

    store.start_session(context.session_id)  # idempotent (INSERT OR IGNORE)
    store.record_activity(
        session_id=context.session_id,
        transcript=stored_transcript,
        tool=call.name,
        args=call.args,
        outcome=outcome,
        speech=result.speech,
        artifact_id=artifact_id,
    )
    store.touch_session(context.session_id)
    context.add_turn(stored_transcript, call.name, result.speech)
