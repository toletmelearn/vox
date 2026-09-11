"""Tier 1: local LLM tool-calling via Ollama (spec Section 7). Runs only
after Tier 0 finds no match and no context-pronoun clarification. Every
failure mode here - timeout, unreachable server, a malformed tool call -
resolves to a RouteResult, never an exception; app.py's escalation logic
treats "no call" the same regardless of why Tier 1 declined.

Note on confidence: Ollama's chat API exposes no native per-call confidence
score for a tool choice. We use a binary signal - 1.0 once a returned call
validates against its tool's pydantic schema, 0.0 otherwise - rather than
inventing a numeric heuristic the spec doesn't define. See DECISIONS.md.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
import ollama
import psutil
from pydantic import BaseModel, ValidationError

from vox.config import get_settings
from vox.router.base import RouteResult, ToolCall
from vox.tools.registry import REGISTRY

logger = logging.getLogger("vox.router.tier1")

# Spec Section 3's literal cutoff is 16.0 GB. Set fractionally below that:
# Windows reports total physical RAM minus a firmware/OS-reserved sliver, so
# a real 16 GB stick commonly shows up as ~15.9 GB to psutil - that's normal
# hardware, not an underpowered machine. Live-verified that qwen3:8b's
# tool-calling works correctly at that exact reported figure (see
# DECISIONS.md Phase 4). 16.0 stays the documented general-case default;
# this is a narrow, evidence-based adjustment for the reporting slack, not a
# loosening of the spec's intent.
MIN_RAM_GB = 15.5

_SYSTEM_PROMPT = (
    "You control a desktop computer through a fixed set of tools. You must "
    "respond only by calling exactly one tool from the list provided - "
    "never with plain text, and never with a tool or argument that isn't "
    "in the schema. If the request is ambiguous, not something any tool "
    "can do, or you are not confident what the user wants, call "
    "ask_clarification with a short question instead of guessing."
)

# Network/server failures that mean "Tier 1 isn't usable right now", not a
# bug in the model's reply. ConnectionError is what the ollama client
# raises (unwrapped, its own builtin) when the server refuses the
# connection; httpx.TimeoutException covers a slow/hung server.
_UNREACHABLE_ERRORS = (ConnectionError, ollama.ResponseError)


def _client() -> ollama.Client:
    settings = get_settings()
    return ollama.Client(timeout=settings.tier1.timeout_s)


def has_enough_ram() -> bool:
    return psutil.virtual_memory().total / (1024**3) >= MIN_RAM_GB


def is_available() -> bool:
    """Whether Tier 1 should be attempted at all: enabled in config, enough
    RAM (spec Section 3: below 16 GB, Tier 0 only), and the Ollama server
    answers. A cheap connectivity probe only - it does not load the model,
    so it stays fast even when the model itself is slow to warm up."""
    settings = get_settings()
    if not settings.tier1.enabled:
        return False
    if not has_enough_ram():
        logger.warning(
            "Tier 1 disabled: this machine has under %.1f GB RAM.", MIN_RAM_GB
        )
        return False
    try:
        ollama.Client(timeout=5).list()
    except httpx.TimeoutException:
        logger.warning("Tier 1 disabled: Ollama did not respond in time.")
        return False
    except _UNREACHABLE_ERRORS:
        logger.warning("Tier 1 disabled: Ollama is not reachable.", exc_info=True)
        return False
    return True


def _tool_call_from_response(response: ollama.ChatResponse) -> tuple[str, dict[str, Any]] | None:
    calls = response.message.tool_calls
    if not calls:
        return None
    call = calls[0]
    return call.function.name, dict(call.function.arguments)


def _chat(messages: list[dict[str, Any]]) -> ollama.ChatResponse:
    settings = get_settings()
    return _client().chat(
        model=settings.tier1.model,
        messages=messages,
        tools=REGISTRY.as_ollama_tools(),
        think=settings.tier1.thinking,
    )


def _validate(name: str, args: dict[str, Any]) -> tuple[BaseModel | None, str | None]:
    registered = REGISTRY.get(name)
    if registered is None:
        return None, f"there is no tool named {name!r}"
    try:
        return registered.args_model(**args), None
    except ValidationError as exc:
        return None, str(exc)


def _clarify(question: str) -> RouteResult:
    return RouteResult(call=None, confidence=0.0, tier="tier1", clarification=question)


def route(text: str) -> RouteResult:
    """Ask the model to pick exactly one tool. Validates the returned args
    against that tool's pydantic schema; on validation failure, retries
    once with the error appended to the conversation (spec Section 7),
    then falls back to clarification rather than guessing."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]

    for attempt in range(2):
        try:
            response = _chat(messages)
        except httpx.TimeoutException:
            logger.warning("Tier 1 call timed out after %ss.", get_settings().tier1.timeout_s)
            return _clarify("That took too long.")
        except _UNREACHABLE_ERRORS:
            logger.warning("Tier 1 call failed.", exc_info=True)
            return _clarify("I couldn't reach the local model.")

        parsed = _tool_call_from_response(response)
        if parsed is None:
            return _clarify("I'm not sure what you meant. Could you rephrase that?")

        name, args = parsed
        validated, error = _validate(name, args)
        if validated is not None:
            return RouteResult(
                call=ToolCall(name=name, args=validated.model_dump()),
                confidence=1.0,
                tier="tier1",
            )

        logger.info("Tier 1 returned an invalid call to %r: %s", name, error)
        if attempt == 0:
            messages.append(response.message.model_dump(exclude_none=True))
            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "content": f"Invalid arguments: {error} Call the tool again with corrected arguments.",
                }
            )

    return _clarify("I'm not sure what you meant. Could you rephrase that?")
