"""Google Gemini provider using the google-genai SDK directly."""

from __future__ import annotations

import os
from typing import Any

from google import genai
from google.genai import types as genai_types

from ._provider_base import DirectProvider, _ParsedResponse
from .registry import get_provider_spec
from .types import (
    CompletionOptions,
    CompletionResult,
    Message,
    MessageRole,
    ToolCall,
    ToolDefinition,
)

_FINISH_REASON_MAP: dict[str, str] = {
    "STOP": "end_turn",
    "MAX_TOKENS": "length",
    "SAFETY": "stop",
    "RECITATION": "stop",
    "LANGUAGE": "stop",
    "OTHER": "stop",
    "BLOCKLIST": "stop",
    "PROHIBITED_CONTENT": "stop",
    "MALFORMED_FUNCTION_CALL": "stop",
    "FINISH_REASON_UNSPECIFIED": "stop",
}


class GoogleProvider(DirectProvider):
    """Google Gemini provider using the google-genai SDK."""

    def __init__(self) -> None:
        super().__init__()
        spec = get_provider_spec("google")
        api_key = os.environ.get(spec.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{spec.api_key_env} environment variable is not set. "
                f"Please set it to your {spec.display_name} API key."
            )
        self._genai_client = genai.Client(api_key=api_key)

    @property
    def name(self) -> str:
        return "google"

    async def _call_api(self, **kwargs: Any) -> Any:
        model = kwargs.pop("model")
        # The retry loop updates kwargs["messages"] (the unified dict list).
        # Rebuild contents from that on every call so retries reach the API correctly.
        raw_messages = kwargs.pop("messages", [])
        config = kwargs.pop("config", None)
        contents = self._raw_messages_to_contents(raw_messages)
        return await self._genai_client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

    def _build_request_kwargs(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> dict[str, Any]:
        # Store messages as plain dicts so the base retry loop can extend them.
        api_messages: list[dict[str, Any]] = [
            {
                "role": msg.role.value if isinstance(msg.role, MessageRole) else str(msg.role),
                "content": msg.content,
            }
            for msg in messages
        ]

        config_kwargs: dict[str, Any] = {"max_output_tokens": options.max_tokens}
        if options.temperature is not None:
            config_kwargs["temperature"] = options.temperature
        if system:
            config_kwargs["system_instruction"] = system
        if options.tools:
            config_kwargs["tools"] = [self._convert_tools_google(options.tools)]
        if options.tool_choice and options.tool_choice.get("type") == "tool":
            config_kwargs["tool_config"] = genai_types.ToolConfig(
                function_calling_config=genai_types.FunctionCallingConfig(
                    mode="ANY",
                    allowed_function_names=[options.tool_choice["name"]],
                )
            )

        return {
            "model": options.model,
            "messages": api_messages,
            "config": genai_types.GenerateContentConfig(**config_kwargs),
            # max_tokens exposed at top level so the retry loop can update it.
            "max_tokens": options.max_tokens,
        }

    def _convert_tools_google(self, tools: list[ToolDefinition]) -> genai_types.Tool:
        declarations = [
            genai_types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=genai_types.Schema(
                    **self._json_schema_to_google(tool.input_schema)
                ),
            )
            for tool in tools
        ]
        return genai_types.Tool(function_declarations=declarations)

    def _json_schema_to_google(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Convert a JSON Schema dict to keyword args for genai_types.Schema."""
        result: dict[str, Any] = {}
        schema_type = schema.get("type")
        if schema_type:
            result["type"] = schema_type.upper()
        if "description" in schema:
            result["description"] = schema["description"]
        if "properties" in schema:
            result["properties"] = {
                k: genai_types.Schema(**self._json_schema_to_google(v))
                for k, v in schema["properties"].items()
            }
        if "required" in schema:
            result["required"] = list(schema["required"])
        if "items" in schema:
            result["items"] = genai_types.Schema(**self._json_schema_to_google(schema["items"]))
        if "enum" in schema:
            result["enum"] = list(schema["enum"])
        return result

    def _raw_messages_to_contents(
        self, messages: list[dict[str, Any]]
    ) -> list[genai_types.Content]:
        """Convert unified message dicts (including retry tool feedback) to Google Content objects."""
        contents: list[genai_types.Content] = []
        for msg in messages:
            role = msg.get("role", "user")
            # Google only accepts "user" and "model" roles.
            google_role = "model" if role == "assistant" else "user"
            content = msg.get("content", "")

            parts: list[genai_types.Part] = []
            if isinstance(content, str):
                if content:
                    parts.append(genai_types.Part(text=content))
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text = block.get("text", "")
                        if text:
                            parts.append(genai_types.Part(text=text))
                    elif btype == "tool_use":
                        parts.append(genai_types.Part(
                            function_call=genai_types.FunctionCall(
                                name=block.get("name", ""),
                                args=block.get("input", {}),
                            )
                        ))
                    elif btype == "tool_result":
                        parts.append(genai_types.Part(
                            function_response=genai_types.FunctionResponse(
                                name=block.get("name", block.get("tool_use_id", "")),
                                response={"result": block.get("content", "")},
                            )
                        ))

            if parts:
                contents.append(genai_types.Content(role=google_role, parts=parts))

        return contents

    def _parse_sdk_response(self, response: Any) -> _ParsedResponse:
        text_blocks: list[str] = []
        tool_calls: list[ToolCall] = []
        assistant_blocks: list[dict[str, Any]] = []

        candidates = getattr(response, "candidates", []) or []
        candidate = candidates[0] if candidates else None

        if candidate:
            content_obj = getattr(candidate, "content", None)
            parts = getattr(content_obj, "parts", []) or []
            for part in parts:
                text = getattr(part, "text", None)
                fc = getattr(part, "function_call", None)
                if text:
                    text_blocks.append(text)
                    assistant_blocks.append({"type": "text", "text": text})
                elif fc is not None:
                    tool_name = getattr(fc, "name", "")
                    tool_args = dict(getattr(fc, "args", {}) or {})
                    call_id = f"call_{tool_name}"
                    tool_calls.append(ToolCall(id=call_id, name=tool_name, input=tool_args))
                    assistant_blocks.append({
                        "type": "tool_use",
                        "id": call_id,
                        "name": tool_name,
                        "input": tool_args,
                    })

        finish_reason_raw = None
        if candidate:
            fr = getattr(candidate, "finish_reason", None)
            finish_reason_raw = getattr(fr, "name", str(fr)) if fr else None
        stop_reason = _FINISH_REASON_MAP.get(finish_reason_raw or "", "stop")

        usage = getattr(response, "usage_metadata", None)
        input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        model = str(getattr(response, "model_version", "") or "")

        result = CompletionResult(
            content="".join(text_blocks) or None,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            stop_reason=stop_reason,
        )
        assistant_message = (
            {"role": "assistant", "content": assistant_blocks} if assistant_blocks else None
        )
        # Use "anthropic" response_format so _build_retry_messages sends
        # tool results as tool_result blocks (Google accepts this natively).
        return _ParsedResponse(
            result=result,
            assistant_message=assistant_message,
            response_format="anthropic",
        )

    async def close(self) -> None:
        pass  # google-genai Client has no explicit async close
