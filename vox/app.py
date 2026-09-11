"""Wires config, logging, the platform adapter, and the guard/audit layer
together. Owns the startup self-check and the --text entry path."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Protocol

import numpy as np
import psutil
from rich.console import Console
from rich.table import Table

import vox.tools  # noqa: F401 - import populates REGISTRY
from vox.config import Settings, get_settings
from vox.logging_setup import setup_logging
from vox.platform import get_adapter
from vox.platform.base import UnsupportedCapability
from vox.router import tier0_grammar, tier1_local
from vox.router.base import RouteResult, ToolCall, Transcript
from vox.security.audit import get_audit_log
from vox.security.jail import JailViolation, jail_roots
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
        return ToolResult(ok=False, speech="I don't have that tool.")

    audit = get_audit_log()
    row_id = audit.write_pending(
        transcript=transcript,
        tool=call.name,
        args=call.args,
        risk=registered.risk,
        tier=tier,
        stt_confidence=stt_confidence,
    )
    start = time.monotonic()
    try:
        validated = registered.args_model(**call.args)
        result = registered.fn(**validated.model_dump())
    except JailViolation as exc:
        audit.update_status(row_id, status="rejected", error=str(exc))
        return ToolResult(ok=False, speech="That location isn't allowed.")
    except Exception as exc:  # noqa: BLE001 - tools must not raise; this is the backstop
        logger.error("tool %s raised unexpectedly", call.name, exc_info=True)
        audit.update_status(row_id, status="failed", error=str(exc))
        return ToolResult(ok=False, speech="Something went wrong.")

    duration_ms = int((time.monotonic() - start) * 1000)
    audit.update_status(
        row_id,
        status="executed" if result.ok else "failed",
        error=None if result.ok else result.detail,
        duration_ms=duration_ms,
    )
    return result


def route_and_execute(transcript: Transcript) -> ToolResult:
    """The shared pipeline both input modes feed (spec Section 6D: "Both
    produce a Transcript... do not fork the pipeline"). Escalation logic
    (spec Section 7): a low-confidence transcript is refused before
    routing; Tier 0 first. A Tier 0 clarification (its context-pronoun
    patterns, e.g. "make that a PDF" with no remembered artifact) is
    returned as-is and never forwarded to Tier 1 - Tier 1 has no more
    context than Tier 0 does until Phase 6's memory store exists, so
    escalating would just trade one unresolved pronoun for a fabricated
    guess (spec Section 7, tier0_grammar module docstring). Only a bare
    "no match" from Tier 0 escalates. Tier 2 is not built until later, so
    anything Tier 1 can't resolve (or Tier 1 being unavailable) ends in
    "didn't understand" for now."""
    settings = get_settings()
    if transcript.confidence < settings.stt.min_confidence:
        return ToolResult(ok=False, speech="Sorry, I didn't catch that.")

    route_result = tier0_grammar.route(transcript.text)

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


def run_self_check(settings: Settings) -> None:
    adapter = get_adapter()
    console = Console()
    table = Table(title="vox startup self-check")
    table.add_column("Check")
    table.add_column("Status")

    for root in jail_roots():
        try:
            root.mkdir(parents=True, exist_ok=True)
            ok = root.exists() and root.is_dir()
        except OSError:
            ok = False
        table.add_row(f"jail root: {root}", "[green]ok[/]" if ok else "[red]missing/unwritable[/]")

    table.add_row("OS", adapter.os_build())
    table.add_row("AVX2", "[green]present[/]" if adapter.cpu_supports_avx2() else "[red]absent[/]")

    ram_gb = psutil.virtual_memory().total / (1024**3)
    table.add_row("RAM", f"{ram_gb:.1f} GB")

    workdir = Path(settings.paths.workdir).expanduser()
    free_gb = shutil.disk_usage(workdir).free / (1024**3)
    table.add_row("Free disk (workdir volume)", f"{free_gb:.1f} GB")

    if settings.tier1.enabled:
        tier1_ok = tier1_local.is_available()
        status = "[green]ollama reachable[/]" if tier1_ok else "[red]unavailable - Tier 0 only[/]"
    else:
        status = "[yellow]disabled in config[/]"
    table.add_row(f"tier 1: {settings.tier1.model}", status)

    for label, chord in (("voice", settings.hotkeys.voice), ("text", settings.hotkeys.text)):
        try:
            hotkey_ok = adapter.verify_hotkey_available(chord)
            status = "[green]available[/]" if hotkey_ok else "[red]already claimed by another app[/]"
        except UnsupportedCapability:
            status = "[yellow]cannot verify on this platform[/]"
        table.add_row(f"hotkey: {label} ({chord})", status)

    all_caps = {
        "list_windows",
        "focus_window",
        "launch",
        "running_processes",
        "open_default_browser",
        "running_browsers",
        "set_volume",
        "lock_screen",
        "screenshot",
        "notify",
        "open_path",
    }
    present = adapter.capabilities()
    for cap in sorted(all_caps):
        status = "[green]present[/]" if cap in present else "[red]absent[/]"
        table.add_row(f"capability: {cap}", status)

    console.print(table)


def bootstrap() -> Settings:
    settings = get_settings()
    setup_logging(settings)
    run_self_check(settings)
    return settings


class VoiceCapture(Protocol):
    def stop(self) -> None: ...


def start_voice_mode(settings: Settings) -> VoiceCapture | None:
    """Wires the voice hotkey to the same pipeline as --text (spec Section
    10, Phase 3). Audio-stack imports are deferred to here, not module
    scope, so a missing/broken mic, PortAudio, or model download never
    breaks the --text path (invariant 9: degrade, never brick; invariant 10:
    text is an equal path, not a fallback). Returns the running capture
    object (call .stop() to release the hotkey), or None if voice mode
    could not start."""
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

    def _on_recorded(pcm: np.ndarray) -> None:
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

    try:
        capture = HotkeyCapture(settings.hotkeys.voice, on_recorded=_on_recorded)
        capture.start()
    except Exception:
        logger.warning("Failed to start the voice hotkey listener.", exc_info=True)
        return None

    logger.info("Voice mode listening on hotkey %r (hold to talk).", settings.hotkeys.voice)
    return capture
