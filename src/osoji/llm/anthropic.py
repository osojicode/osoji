"""Anthropic provider using the anthropic SDK directly."""

from __future__ import annotations

import logging
import os
from typing import Any

import anthropic

from ._provider_base import DirectProvider, _ParsedResponse
from .registry import get_provider_spec
from .types import CompletionOptions, Message, MessageRole

logger = logging.getLogger(__name__)

# Opt-in request knobs, read once per provider. Unset means the model's own
# default, which is what every shipped run has used.
ENV_THINKING = "OSOJI_THINKING"
ENV_EFFORT = "OSOJI_EFFORT"
_THINKING_MODES = ("adaptive",)
_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# Thinking tokens count against max_tokens, and call sites size max_tokens
# for the answer alone (1_024 to 4_096). Provisional: the benchmark's cost
# column decides it (osojicode/work#108).
THINKING_MAX_TOKENS_FLOOR = 8_192

# A model's 400 for a request feature it does not take, matched on the API's
# own message. Learned per model for the provider's lifetime instead of kept
# in a model table: Opus 5.5 / Sonnet 5.5 / Fable 5.1 refuse a forced tool,
# Haiku 4.5 refuses adaptive thinking and the effort parameter.
_FEATURE_REJECTIONS = (
    ("forced_tool_choice", 'tool_choice: type "tool" and "any" are not supported'),
    ("thinking", "thinking is not supported on this model"),
    ("effort", "does not support the effort parameter"),
    # A level the model lacks (Sonnet 4.6 has no xhigh): the model's default
    # effort is used instead, with a warning.
    ("effort", "does not support effort level"),
)


def _read_knob(name: str, allowed: tuple[str, ...]) -> str | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    if raw not in allowed:
        raise RuntimeError(f"{name}={raw!r} is not one of: {', '.join(allowed)}")
    return raw


def request_knobs_stamp() -> str:
    """The opt-in knobs as a stable string ("" when none are set), for cache keys."""
    thinking = _read_knob(ENV_THINKING, _THINKING_MODES)
    effort = _read_knob(ENV_EFFORT, _EFFORT_LEVELS)
    return ";".join(f"{k}={v}" for k, v in (("thinking", thinking), ("effort", effort)) if v)


def _error_text(exc: BaseException) -> str:
    parts = [str(exc), str(getattr(exc, "message", "") or "")]
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            parts.append(str(error.get("message") or ""))
    return " ".join(parts)


def _tool_instruction(tool_choice: dict[str, Any]) -> str:
    if tool_choice.get("type") == "tool":
        return f"Respond by calling the `{tool_choice.get('name')}` tool exactly once."
    return "Respond by calling one of the provided tools."


class AnthropicProvider(DirectProvider):
    """Anthropic Claude provider using the anthropic SDK."""

    # Haiku 4.5 accepts at most 64K output tokens; Sonnet 4.6 and Opus 4.6
    # accept 128K. One provider-wide cap at the binding (smallest) tier keeps
    # every tier safe without a per-model table that drifts as models change
    # (osojicode/work#104: doc_prompts asked for 156_200 and got a 400).
    max_output_tokens = 64_000

    def __init__(self) -> None:
        super().__init__()
        spec = get_provider_spec("anthropic")
        api_key = os.environ.get(spec.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{spec.api_key_env} environment variable is not set. "
                f"Please set it to your {spec.display_name} API key."
            )
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._thinking = _read_knob(ENV_THINKING, _THINKING_MODES)
        self._effort = _read_knob(ENV_EFFORT, _EFFORT_LEVELS)
        self._unsupported: dict[str, set[str]] = {}

    @property
    def name(self) -> str:
        return "anthropic"

    async def _call_api(self, **kwargs: Any) -> Any:
        return await self._client.messages.create(**kwargs)

    def _build_request_kwargs(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> dict[str, Any]:
        api_messages = [
            {
                "role": msg.role.value if isinstance(msg.role, MessageRole) else str(msg.role),
                "content": msg.content,
            }
            for msg in messages
        ]
        kwargs: dict[str, Any] = {
            "model": options.model,
            "messages": api_messages,
            "max_tokens": options.max_tokens,
        }
        if system:
            # cache_control on the system prompt enables Anthropic's prompt caching.
            # The system prompt is stable across audit calls and benefits most from caching.
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        if options.temperature is not None:
            kwargs["temperature"] = options.temperature
        if options.tools:
            kwargs["tools"] = self._convert_tools_anthropic(options.tools)
        if options.tool_choice:
            tc = options.tool_choice
            if tc.get("type") == "tool":
                kwargs["tool_choice"] = {"type": "tool", "name": tc["name"]}
            elif tc.get("type") in {"auto", "any"}:
                kwargs["tool_choice"] = {"type": tc["type"]}
        kwargs["timeout"] = self.llm_timeout
        return kwargs

    def _plan(self, model: str | None, tool_choice_type: str | None) -> tuple[str | None, str | None, bool]:
        """(thinking, effort, downgrade) for a request to ``model``.

        A forced tool is sent as ``auto`` plus an instruction when the model
        refuses forced choice, or when thinking is requested: a forced tool
        makes the 4.6 models skip thinking even when it is asked for. The
        call site's tool_choice still decides which tool the retry loop
        requires.
        """
        unsupported = self._unsupported.get(model or "", set())
        thinking = self._thinking if "thinking" not in unsupported else None
        effort = self._effort if "effort" not in unsupported else None
        # Only a named tool is downgraded for thinking: the retry loop
        # enforces a named tool, not "any" (no call site uses "any"; it is
        # downgraded only where the model refuses it outright).
        downgrade = (tool_choice_type == "tool" and thinking is not None) or (
            tool_choice_type in ("tool", "any") and "forced_tool_choice" in unsupported
        )
        return thinking, effort, downgrade

    def planned_max_tokens(self, options: CompletionOptions) -> int:
        base = super().planned_max_tokens(options)
        thinking, _, downgrade = self._plan(options.model, (options.tool_choice or {}).get("type"))
        if thinking is None and not downgrade:
            return base
        return self._clamp_max_tokens(max(base, THINKING_MAX_TOKENS_FLOOR))

    def _wire_request_kwargs(self, request_kwargs: dict[str, Any]) -> dict[str, Any]:
        tool_choice = request_kwargs.get("tool_choice") or {}
        thinking, effort, downgrade = self._plan(request_kwargs.get("model"), tool_choice.get("type"))
        if thinking is None and effort is None and not downgrade:
            return request_kwargs
        wire = dict(request_kwargs)
        if downgrade:
            wire["tool_choice"] = {"type": "auto"}
            # A second block after the cached system block keeps its cache.
            wire["system"] = [
                *(request_kwargs.get("system") or []),
                {"type": "text", "text": _tool_instruction(tool_choice)},
            ]
        # Sent through extra_body so they reach the API on any SDK version the
        # dependency floor admits; older SDKs reject them as keyword arguments.
        extra_body = dict(request_kwargs.get("extra_body") or {})
        if thinking is not None:
            extra_body["thinking"] = {"type": thinking}
        if effort is not None:
            extra_body["output_config"] = {"effort": effort}
        if extra_body:
            wire["extra_body"] = extra_body
        if thinking is not None or downgrade:
            # A downgraded call goes to a model that may think on its own.
            wire["max_tokens"] = self._clamp_max_tokens(max(wire["max_tokens"], THINKING_MAX_TOKENS_FLOOR))
        return wire

    def _learn_from_rejection(self, wire_kwargs: dict[str, Any], exc: BaseException) -> bool:
        if getattr(exc, "status_code", None) != 400:
            return False
        text = _error_text(exc)
        model = wire_kwargs.get("model") or ""
        body = wire_kwargs.get("extra_body") or {}
        sent = {
            "forced_tool_choice": (wire_kwargs.get("tool_choice") or {}).get("type") in ("tool", "any"),
            "thinking": "thinking" in body,
            "effort": "effort" in (body.get("output_config") or {}),
        }
        for feature, marker in _FEATURE_REJECTIONS:
            if marker in text and sent[feature]:
                self._unsupported.setdefault(model, set()).add(feature)
                logger.warning("%s does not take %s; sending without it from now on", model, feature)
                return True
        return False

    def _parse_sdk_response(self, response: Any) -> _ParsedResponse:
        return self._parse_anthropic_response(response)

    async def close(self) -> None:
        await self._client.close()
