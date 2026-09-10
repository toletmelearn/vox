"""The @tool decorator and REGISTRY. Every tool is a small, typed function;
the LLM only ever chooses a name and fills typed arguments — see spec
Section 5 and the architectural rule in Section 2."""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, Literal, get_args, get_origin, get_type_hints

from pydantic import BaseModel, create_model

Risk = Literal["safe", "medium", "destructive"]

_ALLOWED_SIMPLE = (str, int, float, bool)


class ToolResult(BaseModel):
    ok: bool
    speech: str
    detail: str = ""
    artifact_path: str | None = None


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    risk: Risk
    description: str
    fn: Callable[..., ToolResult]
    args_model: type[BaseModel]


class ToolRegistry(dict[str, RegisteredTool]):
    def as_ollama_tools(self) -> list[dict[str, Any]]:
        """JSON-schema tool list for Ollama's `tools=` parameter, generated
        from the registered signatures. Never hand-write this schema."""
        entries = []
        for reg in self.values():
            entries.append(
                {
                    "type": "function",
                    "function": {
                        "name": reg.name,
                        "description": reg.description,
                        "parameters": reg.args_model.model_json_schema(),
                    },
                }
            )
        return entries


REGISTRY = ToolRegistry()


def _check_param_type(tool_name: str, param_name: str, annotation: Any) -> None:
    if get_origin(annotation) is Literal:
        return
    if get_origin(annotation) is list:
        if get_args(annotation) == (str,):
            return
        raise TypeError(
            f"tool {tool_name!r} parameter {param_name!r}: list type must be list[str]"
        )
    if annotation in _ALLOWED_SIMPLE:
        return
    raise TypeError(
        f"tool {tool_name!r} parameter {param_name!r} has disallowed type "
        f"{annotation!r}; must be one of str|int|float|bool|list[str]|Literal[...]"
    )


def tool(
    *, name: str, risk: Risk, description: str
) -> Callable[[Callable[..., ToolResult]], Callable[..., ToolResult]]:
    """Decorator. Registers fn in REGISTRY with a pydantic-derived JSON schema
    built from the function's type hints. Enforces:
      - every parameter is annotated
      - every parameter type is str | int | float | bool | list[str] | Literal[...]
      - the return type is ToolResult
    Raises at import time if violated."""

    def decorator(fn: Callable[..., ToolResult]) -> Callable[..., ToolResult]:
        sig = inspect.signature(fn)
        hints = get_type_hints(fn)

        fields: dict[str, Any] = {}
        for pname, param in sig.parameters.items():
            if param.annotation is inspect.Parameter.empty:
                raise TypeError(f"tool {name!r} parameter {pname!r} is not annotated")
            annotation = hints.get(pname, param.annotation)
            _check_param_type(name, pname, annotation)
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[pname] = (annotation, default)

        return_annotation = hints.get("return", sig.return_annotation)
        if return_annotation is not ToolResult:
            raise TypeError(
                f"tool {name!r} must return ToolResult, got {return_annotation!r}"
            )

        if name in REGISTRY:
            raise ValueError(f"duplicate tool name: {name!r}")

        args_model = create_model(f"{fn.__name__.title().replace('_', '')}Args", **fields)

        REGISTRY[name] = RegisteredTool(
            name=name,
            risk=risk,
            description=description,
            fn=fn,
            args_model=args_model,
        )
        return fn

    return decorator
