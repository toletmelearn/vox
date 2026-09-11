"""Tier 1 (local LLM) router tests (spec Section 10, Phase 4 acceptance).
Every test here mocks the Ollama client/response layer - no test may
require a running model or make a network connection (spec Section 13)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from docx import Document
from ollama import ChatResponse, Message

from vox.app import handle_text
from vox.router import tier1_local
from vox.router.base import RouteResult, ToolCall


def _response(name: str, arguments: dict[str, object]) -> ChatResponse:
    message = Message(
        role="assistant",
        tool_calls=[Message.ToolCall(function=Message.ToolCall.Function(name=name, arguments=arguments))],
    )
    return ChatResponse(model="qwen3:8b", message=message)


def _no_call_response() -> ChatResponse:
    return ChatResponse(model="qwen3:8b", message=Message(role="assistant", content="I don't know."))


# --- route(): a valid tool call --------------------------------------------


def test_route_returns_validated_tool_call(monkeypatch):
    monkeypatch.setattr(tier1_local, "_chat", lambda messages: _response("web_search", {"query": "laravel queues"}))

    result = tier1_local.route("search for laravel queues please")

    assert result.tier == "tier1"
    assert result.confidence == 1.0
    assert result.call == ToolCall(name="web_search", args={"query": "laravel queues"})


# --- acceptance: unsupported request -> ask_clarification, not a fabrication


def test_unsupported_request_calls_ask_clarification(monkeypatch):
    question = "I can't book flights. Is there something else I can help with?"
    monkeypatch.setattr(tier1_local, "_chat", lambda messages: _response("ask_clarification", {"question": question}))

    result = tier1_local.route("book me a flight to Goa")

    assert result.call is not None
    assert result.call.name == "ask_clarification"
    assert result.call.args == {"question": question}


# --- acceptance: malformed call retried once, then falls back -------------


def test_malformed_call_retried_once_then_falls_back(monkeypatch):
    calls = [
        _response("web_search", {}),  # missing required 'query' -> invalid
        _response("web_search", {}),  # still invalid on retry
    ]
    seen_messages: list[list[dict[str, object]]] = []

    def fake_chat(messages: list[dict[str, object]]) -> ChatResponse:
        seen_messages.append(list(messages))
        return calls[len(seen_messages) - 1]

    monkeypatch.setattr(tier1_local, "_chat", fake_chat)

    result = tier1_local.route("search for something")

    assert len(seen_messages) == 2  # exactly one retry
    assert result.call is None
    assert result.clarification is not None
    # the retry must carry the validation error back to the model
    assert any(m.get("role") == "tool" for m in seen_messages[1])


def test_malformed_call_retried_once_then_succeeds(monkeypatch):
    calls = [
        _response("web_search", {}),  # missing required 'query'
        _response("web_search", {"query": "corrected"}),  # valid on retry
    ]
    call_count = {"n": 0}

    def fake_chat(messages: list[dict[str, object]]) -> ChatResponse:
        response = calls[call_count["n"]]
        call_count["n"] += 1
        return response

    monkeypatch.setattr(tier1_local, "_chat", fake_chat)

    result = tier1_local.route("search for something")

    assert call_count["n"] == 2
    assert result.call == ToolCall(name="web_search", args={"query": "corrected"})


def test_unknown_tool_name_treated_as_invalid_and_retried(monkeypatch):
    monkeypatch.setattr(tier1_local, "_chat", lambda messages: _response("delete_everything", {}))

    result = tier1_local.route("do something destructive")

    assert result.call is None
    assert result.clarification is not None


def test_no_tool_call_in_response_returns_clarification(monkeypatch):
    monkeypatch.setattr(tier1_local, "_chat", lambda messages: _no_call_response())

    result = tier1_local.route("hello there")

    assert result.call is None
    assert result.clarification is not None


# --- timeout / unreachable server ------------------------------------------


def test_timeout_returns_took_too_long(monkeypatch):
    def raise_timeout(messages: list[dict[str, object]]) -> ChatResponse:
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(tier1_local, "_chat", raise_timeout)

    result = tier1_local.route("do something slow")

    assert result.call is None
    assert result.clarification == "That took too long."


def test_unreachable_server_returns_clarification(monkeypatch):
    def raise_connection_error(messages: list[dict[str, object]]) -> ChatResponse:
        raise ConnectionError("no server")

    monkeypatch.setattr(tier1_local, "_chat", raise_connection_error)

    result = tier1_local.route("do something")

    assert result.call is None
    assert result.clarification is not None


# --- is_available() ---------------------------------------------------------


def test_is_available_false_when_disabled_in_config(jail_settings, mocker):
    jail_settings.tier1.enabled = False
    spy = mocker.patch("vox.router.tier1_local.ollama.Client")

    assert tier1_local.is_available() is False
    spy.assert_not_called()


def test_is_available_false_when_ram_too_low(jail_settings, monkeypatch, mocker):
    jail_settings.tier1.enabled = True
    monkeypatch.setattr(tier1_local, "has_enough_ram", lambda: False)
    spy = mocker.patch("vox.router.tier1_local.ollama.Client")

    assert tier1_local.is_available() is False
    spy.assert_not_called()


def test_is_available_false_and_warns_when_ollama_unreachable(jail_settings, monkeypatch, mocker, caplog):
    jail_settings.tier1.enabled = True
    monkeypatch.setattr(tier1_local, "has_enough_ram", lambda: True)

    fake_client = mocker.MagicMock()
    fake_client.list.side_effect = ConnectionError("refused")
    mocker.patch("vox.router.tier1_local.ollama.Client", return_value=fake_client)

    with caplog.at_level("WARNING"):
        available = tier1_local.is_available()

    assert available is False
    assert any("not reachable" in record.message for record in caplog.records)


def test_is_available_true_when_reachable(jail_settings, monkeypatch, mocker):
    jail_settings.tier1.enabled = True
    monkeypatch.setattr(tier1_local, "has_enough_ram", lambda: True)

    fake_client = mocker.MagicMock()
    fake_client.list.return_value = {"models": []}
    mocker.patch("vox.router.tier1_local.ollama.Client", return_value=fake_client)

    assert tier1_local.is_available() is True


# --- end-to-end through app.py's escalation logic (still fully mocked) -----


def test_app_escalates_unmatched_text_to_ask_clarification(jail_settings, audit_log, monkeypatch):
    question = "I can't book flights. Anything else?"
    monkeypatch.setattr(tier1_local, "is_available", lambda: True)
    monkeypatch.setattr(
        tier1_local,
        "route",
        lambda text: RouteResult(
            call=ToolCall(name="ask_clarification", args={"question": question}),
            confidence=1.0,
            tier="tier1",
        ),
    )

    result = handle_text("book me a flight to Goa")

    assert result.ok
    assert result.speech == question
    row = audit_log._conn.execute("SELECT tier, tool, status FROM events").fetchone()
    assert row == ("tier1", "ask_clarification", "executed")


def test_app_creates_word_document_with_headed_sections(jail_settings, audit_log, monkeypatch):
    sections = [
        "Overview|Photosynthesis turns light into chemical energy.",
        "Light Reactions|Chlorophyll absorbs sunlight in the chloroplast.",
        "Calvin Cycle|Carbon dioxide is fixed into sugar.",
        "Importance|It is the base of most food chains.",
    ]
    monkeypatch.setattr(tier1_local, "is_available", lambda: True)
    monkeypatch.setattr(
        tier1_local,
        "route",
        lambda text: RouteResult(
            call=ToolCall(
                name="create_word_document",
                args={
                    "filename": "Photosynthesis",
                    "title": "Photosynthesis",
                    "sections": sections,
                    "parent": "documents",
                },
            ),
            confidence=1.0,
            tier="tier1",
        ),
    )

    result = handle_text("make me a word document explaining photosynthesis for class 8")

    assert result.ok
    path = Path(jail_settings.paths.documents, "Photosynthesis.docx")
    assert path.exists()

    doc = Document(str(path))
    heading_1s = [p.text for p in doc.paragraphs if p.style is not None and p.style.name == "Heading 1"]
    assert len(heading_1s) >= 3


def test_app_falls_back_to_tier0_only_when_ollama_unreachable(jail_settings, audit_log, monkeypatch, caplog):
    jail_settings.tier1.enabled = True
    monkeypatch.setattr(tier1_local, "has_enough_ram", lambda: True)

    with pytest.MonkeyPatch.context() as mp:
        import unittest.mock as mock

        fake_client = mock.MagicMock()
        fake_client.list.side_effect = ConnectionError("refused")
        mp.setattr("vox.router.tier1_local.ollama.Client", lambda *a, **k: fake_client)

        with caplog.at_level("WARNING"):
            # Tier 0 still handles a matching command with no LLM involved.
            time_result = handle_text("what's the time")
            # An unmatched command degrades to "didn't understand", not a crash.
            unmatched_result = handle_text("book me a flight to Goa")

    assert time_result.ok
    assert not unmatched_result.ok
    assert unmatched_result.speech == "I didn't understand that."
    assert any("not reachable" in record.message for record in caplog.records)
