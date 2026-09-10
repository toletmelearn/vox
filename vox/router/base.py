"""Core router contracts. Everything else in the router depends on these —
see spec Section 5. Tier 0 grammar (router/tier0_grammar.py) lands in
Phase 2; this module only defines the shared shapes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class Transcript:
    text: str
    confidence: float  # 0..1, derived from whisper avg_logprob; 1.0 for text input
    language: str
    duration_s: float


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class RouteResult:
    call: ToolCall | None
    confidence: float
    tier: Literal["tier0", "tier1", "tier2", "none"]
    clarification: str | None = None
