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


ContextAction = Literal["open", "convert_to_pdf"]


@dataclass
class RouteResult:
    call: ToolCall | None
    confidence: float
    tier: Literal["tier0", "tier1", "tier2", "none"]
    clarification: str | None = None
    # Set only by Tier 0's context-pronoun patterns ("open it", "make that a
    # pdf"). tier0_grammar.py stays context-free (pure, offline, no
    # singleton access - see its module docstring and tests/test_grammar.py)
    # and always pairs this with a clarification; app.py's route_and_execute
    # is the only place that resolves it against the real Context singleton,
    # replacing the clarification with a real call when the last artifact
    # exists and hasn't expired (spec Section 6C).
    context_action: ContextAction | None = None
