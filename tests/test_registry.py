"""@tool decorator contract tests: schema generation and the import-time
guarantees from spec Section 5 / CLAUDE.md invariant."""
from __future__ import annotations

from typing import Literal

import pytest

from vox.tools.registry import REGISTRY, ToolResult, tool


def test_unannotated_parameter_raises_at_decoration_time():
    with pytest.raises(TypeError):

        @tool(name="test_bad_tool_unannotated", risk="safe", description="x")
        def bad(name) -> ToolResult:  # type: ignore[no-untyped-def]
            return ToolResult(ok=True, speech="x")


def test_disallowed_param_type_raises():
    with pytest.raises(TypeError):

        @tool(name="test_bad_tool_dict", risk="safe", description="x")
        def bad(data: dict[str, str]) -> ToolResult:
            return ToolResult(ok=True, speech="x")


def test_non_toolresult_return_raises():
    with pytest.raises(TypeError):

        @tool(name="test_bad_tool_return", risk="safe", description="x")
        def bad(name: str) -> str:  # type: ignore[return-value]
            return "x"


def test_valid_tool_registers_and_builds_schema():
    @tool(name="test_good_tool", risk="safe", description="does a thing")
    def good(name: str, count: int = 3) -> ToolResult:
        return ToolResult(ok=True, speech="ok")

    assert "test_good_tool" in REGISTRY
    schemas = REGISTRY.as_ollama_tools()
    names = [s["function"]["name"] for s in schemas]
    assert "test_good_tool" in names


def test_literal_and_list_str_param_types_are_allowed():
    @tool(name="test_literal_tool", risk="safe", description="x")
    def good(scope: Literal["a", "b"], items: list[str]) -> ToolResult:
        return ToolResult(ok=True, speech="ok")

    assert "test_literal_tool" in REGISTRY


def test_duplicate_tool_name_raises():
    @tool(name="test_dup_tool", risk="safe", description="first")
    def first() -> ToolResult:
        return ToolResult(ok=True, speech="x")

    with pytest.raises(ValueError):

        @tool(name="test_dup_tool", risk="safe", description="second")
        def second() -> ToolResult:
            return ToolResult(ok=True, speech="x")
