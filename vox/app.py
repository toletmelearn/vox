"""Wires config, logging, the platform adapter, and the guard/audit layer
together. Owns the startup self-check and the --text entry path."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Literal, Protocol

import numpy as np

import vox.tools  # noqa: F401 - import populates REGISTRY
from vox.config import Settings, get_settings
from vox.logging_setup import setup_logging
from vox.memory.context import get_context
from vox.memory.tracking import record_execution
from vox.memory.tree import run_startup_maintenance
from vox.platform import get_adapter
from vox.platform.base import UnsupportedCapability
from vox.router import tier0_grammar, tier1_local
from vox.router.base import ContextAction, RouteResult, ToolCall, Transcript
from vox.security import confirm
from vox.security.audit import get_audit_log
from vox.security.jail import JailViolation
from vox.selfcheck import run_self_check
from vox.tools.registry import REGISTRY, ToolResult

logger = logging.getLogger("vox.app")


def execute_tool_call(
    call: ToolCall, *, transcript: str, tier: str = "text", stt_confidence: float = 1.0
) -> ToolResult:
    """Guard layer: write the audit row before execution, run the tool
    through jail validation, update the row after. JailViolation is the only
    exception allowed to propagate out of a tool (spec Section 12); it is
    caught here and recorded as 'rejected'."""
    registered = REGISTRY.get(call.name)
    if registered is None:
        result = ToolResult(ok=False, speech="I don't have that tool.")
        record_execution(call, transcript=transcript, outcome="failed", result=result)
        return result

    audit = get_audit_log()
    row_id = audit.write_pending(
        transcript=transcript,
        tool=call.name,
        args=call.args,
        risk=registered.risk,
        tier=tier,
        stt_confidence=stt_confidence,
    )

    if registered.risk == "destructive":
        # Block on a modal confirmation, default Cancel, never auto-confirmed
        # (spec Section 8.4). The row is already written as 'pending' above,
        # never edited-in-place before this point - only its terminal status
        # changes here.
        if not confirm.confirm_destructive(call.name, call.args):
            audit.update_status(row_id, status="cancelled")
            result = ToolResult(ok=False, speech="Cancelled.")
            record_execution(call, transcript=transcript, outcome="cancelled", result=result)
            return result

    start = time.monotonic()
    try:
        validated = registered.args_model(**call.args)
        result = registered.fn(**validated.model_dump())
    except JailViolation as exc:
        audit.update_status(row_id, status="rejected", error=str(exc))
        result = ToolResult(ok=False, speech="That location isn't allowed.")
        record_execution(call, transcript=transcript, outcome="failed", result=result)
        return result
    except Exception as exc:  # noqa: BLE001 - tools must not raise; this is the backstop
        logger.error("tool %s raised unexpectedly", call.name, exc_info=True)
        audit.update_status(row_id, status="failed", error=str(exc))
        result = ToolResult(ok=False, speech="Something went wrong.")
        record_execution(call, transcript=transcript, outcome="failed", result=result)
        return result

    duration_ms = int((time.monotonic() - start) * 1000)
    audit.update_status(
        row_id,
        status="executed" if result.ok else "failed",
        error=None if result.ok else result.detail,
        duration_ms=duration_ms,
    )

    if registered.risk == "medium" and result.ok and result.artifact_path:
        settings = get_settings()
        confirm.arm_undo(call.name, result.artifact_path, settings.security.undo_window_s)

    record_execution(call, transcript=transcript, outcome="ok" if result.ok else "failed", result=result)
    return result


_CONTEXT_ACTION_TOOL: dict[ContextAction, str] = {
    "open": "open_path",
    "convert_to_pdf": "convert_to_pdf",
}


def _resolve_context_action(action: ContextAction, settings: Settings) -> RouteResult | None:
    """Resolve a Tier 0 context-pronoun match ("open it", "make that a pdf")
    against the real Context singleton (spec Section 6C). Returns None -
    caller keeps the original clarification - when there's no remembered
    artifact, or it's past `memory.context_ttl_minutes`; deliberately checked
    without touching the context first, so an expired artifact stays expired
    rather than being silently refreshed by the act of asking about it."""
    artifact = get_context().last_artifact
    if artifact is None or get_context().is_expired(settings.memory.context_ttl_minutes):
        return None
    return RouteResult(
        call=ToolCall(name=_CONTEXT_ACTION_TOOL[action], args={"path": artifact.path}),
        confidence=0.95,
        tier="tier0",
    )


def route_and_execute(transcript: Transcript) -> ToolResult:
    """The shared pipeline both input modes feed (spec Section 6D: "Both
    produce a Transcript... do not fork the pipeline"). Escalation logic
    (spec Section 7): a low-confidence transcript is refused before
    routing; Tier 0 first. A Tier 0 clarification whose context_action
    resolves against the real Context singleton (spec Section 6C) becomes a
    real call here; one that doesn't resolve (no remembered artifact, or
    past context_ttl_minutes) is returned as-is and never forwarded to Tier
    1 - Tier 1 has no more context than Tier 0 does, so escalating would
    just trade one unresolved pronoun for a fabricated guess (spec Section
    7, tier0_grammar module docstring). Only a bare "no match" from Tier 0
    escalates. Tier 2 is not built until later, so anything Tier 1 can't
    resolve (or Tier 1 being unavailable) ends in "didn't understand" for
    now."""
    confirm.get_kill_switch().clear()  # a new command always starts un-aborted

    settings = get_settings()
    if transcript.confidence < settings.stt.min_confidence:
        return ToolResult(ok=False, speech="Sorry, I didn't catch that.")

    route_result = tier0_grammar.route(transcript.text)

    if route_result.context_action is not None:
        resolved = _resolve_context_action(route_result.context_action, settings)
        if resolved is not None:
            route_result = resolved

    if route_result.call is None and route_result.clarification is None:
        if tier1_local.is_available():
            route_result = tier1_local.route(transcript.text)
            if route_result.call is not None and route_result.confidence < settings.tier1.min_confidence:
                route_result = RouteResult(
                    call=None,
                    confidence=route_result.confidence,
                    tier="tier1",
                    clarification="I'm not sure what you meant. Could you rephrase that?",
                )

    if route_result.clarification is not None:
        return ToolResult(ok=False, speech=route_result.clarification)
    if route_result.call is None:
        return ToolResult(ok=False, speech="I didn't understand that.")

    return execute_tool_call(
        route_result.call,
        transcript=transcript.text,
        tier=route_result.tier,
        stt_confidence=transcript.confidence,
    )


def handle_text(text: str) -> ToolResult:
    """Text input path (spec Section 6D): confidence fixed at 1.0, feeds the
    same pipeline as voice."""
    transcript = Transcript(text=text, confidence=1.0, language="unknown", duration_s=0.0)
    return route_and_execute(transcript)


def handle_transcript(transcript: Transcript) -> ToolResult:
    """Voice input path: transcript.confidence comes from Whisper's
    avg_logprob."""
    return route_and_execute(transcript)


def bootstrap() -> Settings:
    settings = get_settings()
    setup_logging(settings)
    run_self_check(settings)
    run_startup_maintenance(settings)  # spec Section 6C: create ~/.vox/ on first run, prune/sweep on every run
    return settings


class VoiceCapture(Protocol):
    def stop(self) -> None: ...


VoiceState = Literal["listening", "thinking", "idle", "error"]


def start_voice_mode(
    settings: Settings, on_state_change: Callable[[VoiceState], None] | None = None
) -> VoiceCapture | None:
    """Wires the voice hotkey to the same pipeline as --text (spec Section
    10, Phase 3). Audio-stack imports are deferred to here, not module
    scope, so a missing/broken mic, PortAudio, or model download never
    breaks the --text path (invariant 9: degrade, never brick; invariant 10:
    text is an equal path, not a fallback). Returns the running capture
    object (call .stop() to release the hotkey), or None if voice mode
    could not start.

    `on_state_change` is an optional hook for vox/ui/tray.py to drive the
    tray icon (idle/listening/thinking/error) - app.py stays UI-agnostic and
    still works with it omitted."""
    try:
        from vox.audio.capture import HotkeyCapture
        from vox.audio.tts import speak
        from vox.audio.vad import has_speech, trim_silence
        from vox.stt.whisper import transcribe
    except ImportError:
        logger.warning("Audio stack unavailable; voice mode disabled.", exc_info=True)
        return None

    # Real OS-level check, not an assumption (spec Section 6E: "pynput
    # registration can fail silently... verify it took"). Confirmed on this
    # dev machine: ctrl+alt+space was silently intercepted by another
    # application before vox's listener ever saw a key event.
    try:
        available = get_adapter().verify_hotkey_available(settings.hotkeys.voice)
    except UnsupportedCapability:
        available = None  # can't verify on this platform; proceed optimistically
    if available is False:
        logger.error(
            "Hotkey %r is already claimed by another application on this "
            "system and could not be registered for vox. Voice mode was "
            "NOT started. Change hotkeys.voice in config.yaml to a "
            "different chord and restart.",
            settings.hotkeys.voice,
        )
        return None

    def _notify(state: VoiceState) -> None:
        if on_state_change is not None:
            try:
                on_state_change(state)
            except Exception:
                logger.warning("on_state_change(%r) raised", state, exc_info=True)

    def _on_recorded(pcm: np.ndarray) -> None:
        end_state: VoiceState = "idle"
        try:
            logger.info("Recorded %.2fs of audio.", len(pcm) / 16000)
            trimmed = trim_silence(pcm)
            if not has_speech(trimmed):
                logger.info("No speech detected in recording; skipping routing.")
                return
            logger.info("VAD kept %.2fs after trimming.", len(trimmed) / 16000)
            transcript = transcribe(trimmed)
            logger.info(
                "Transcript: %r (confidence=%.2f, language=%s)",
                transcript.text,
                transcript.confidence,
                transcript.language,
            )
            result = handle_transcript(transcript)
            logger.info("Result: ok=%s speech=%r", result.ok, result.speech)
            speak(result.speech)
        except Exception:
            logger.error("voice pipeline raised", exc_info=True)
            end_state = "error"
        finally:
            _notify(end_state)

    try:
        capture = HotkeyCapture(
            settings.hotkeys.voice,
            on_recorded=_on_recorded,
            on_start=lambda: _notify("listening"),
            on_stop=lambda: _notify("thinking"),
        )
        capture.start()
    except Exception:
        logger.warning("Failed to start the voice hotkey listener.", exc_info=True)
        return None

    logger.info("Voice mode listening on hotkey %r (hold to talk).", settings.hotkeys.voice)
    return capture
