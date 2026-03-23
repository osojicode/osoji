"""LLM provider that uses the locally installed Claude Code CLI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any
from uuid import uuid4

from .base import LLMProvider
from .types import (
    CompletionOptions,
    CompletionResult,
    Message,
    MessageRole,
    RequiredToolCallError,
    ToolCall,
    ToolDefinition,
    ToolSchemaValidationError,
)
from .validate import validate_tool_input

_MAX_TOOL_VALIDATION_ATTEMPTS = 3
_DEFAULT_LLM_TIMEOUT = 1200

logger = logging.getLogger(__name__)


class ClaudeCodeCLIError(RuntimeError):
    """Raised when the Claude Code CLI returns an error."""

    def __init__(
        self,
        *,
        exit_code: int,
        stderr: str,
        command: list[str],
    ) -> None:
        self.exit_code = exit_code
        self.stderr = stderr
        self.command = command
        super().__init__(
            f"Claude Code CLI exited with code {exit_code}: {stderr.strip()}"
        )


class ClaudeCodeProvider(LLMProvider):
    """LLM provider that routes requests through the Claude Code CLI.

    Uses ``claude -p`` in non-interactive mode with ``--json-schema`` for
    structured output.  This lets users leverage their Claude subscription
    quota instead of paying per-token API charges.
    """

    def __init__(self, *, claude_path: str | None = None) -> None:
        resolved = claude_path or os.environ.get("OSOJI_CLAUDE_PATH")
        if not resolved:
            resolved = shutil.which("claude")
        if not resolved:
            raise RuntimeError(
                "Claude Code CLI not found. Install it "
                "(https://docs.anthropic.com/en/docs/claude-code) "
                "or set OSOJI_CLAUDE_PATH to the binary location."
            )
        self._claude_path = resolved

    @property
    def name(self) -> str:
        return "claude-code"

    async def complete(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> CompletionResult:
        prompt = self._serialize_messages(messages)
        forced_tool = self._get_forced_tool(options)

        if forced_tool:
            prompt = self._inject_tool_description(prompt, forced_tool)

        result = await self._execute_and_parse(prompt, system, options, forced_tool)

        if forced_tool is None:
            return result

        # --- tool validation / retry loop ---
        total_input = result.input_tokens
        total_output = result.output_tokens
        attempts = 1

        while True:
            if not result.tool_calls:
                if attempts >= _MAX_TOOL_VALIDATION_ATTEMPTS:
                    raise RequiredToolCallError(
                        tool_name=forced_tool.name,
                        attempts=attempts,
                        stop_reason=result.stop_reason,
                    )
                prompt = self._append_missing_tool_feedback(prompt, forced_tool)
                result = await self._execute_and_parse(
                    prompt, system, options, forced_tool,
                )
                total_input += result.input_tokens
                total_output += result.output_tokens
                attempts += 1
                continue

            errors = self._validate_tool_calls(
                result.tool_calls, options,
            )
            if not errors:
                return CompletionResult(
                    content=result.content,
                    tool_calls=result.tool_calls,
                    input_tokens=total_input,
                    output_tokens=total_output,
                    model=result.model,
                    stop_reason=result.stop_reason,
                )

            if attempts >= _MAX_TOOL_VALIDATION_ATTEMPTS:
                raise ToolSchemaValidationError(
                    tool_errors=errors,
                    attempts=attempts,
                )

            prompt = self._append_validation_feedback(prompt, errors)
            result = await self._execute_and_parse(
                prompt, system, options, forced_tool,
            )
            total_input += result.input_tokens
            total_output += result.output_tokens
            attempts += 1

    async def close(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Message serialization
    # ------------------------------------------------------------------

    def _serialize_messages(self, messages: list[Message]) -> str:
        if (
            len(messages) == 1
            and messages[0].role == MessageRole.USER
        ):
            return self._content_to_str(messages[0].content)

        parts: list[str] = []
        for msg in messages:
            label = {
                MessageRole.USER: "User",
                MessageRole.ASSISTANT: "Assistant",
                MessageRole.SYSTEM: "System",
            }.get(msg.role, str(msg.role))  # type: ignore[arg-type]
            parts.append(f"[{label}]\n{self._content_to_str(msg.content)}")
        return "\n\n".join(parts)

    @staticmethod
    def _content_to_str(content: str | list[dict[str, Any]]) -> str:
        if isinstance(content, str):
            return content
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type", "text") == "text":
                    text_parts.append(block.get("text", ""))
                else:
                    text_parts.append(json.dumps(block))
            else:
                text_parts.append(str(block))
        return "\n".join(text_parts)

    # ------------------------------------------------------------------
    # Tool helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_forced_tool(options: CompletionOptions) -> ToolDefinition | None:
        if not options.tool_choice:
            return None
        if options.tool_choice.get("type") != "tool":
            return None
        tool_name = options.tool_choice.get("name")
        if not tool_name:
            return None
        for tool in options.tools:
            if tool.name == tool_name:
                return tool
        return None

    @staticmethod
    def _inject_tool_description(prompt: str, tool: ToolDefinition) -> str:
        return (
            f"{prompt}\n\n"
            f"You must respond with structured data for the tool \"{tool.name}\".\n"
            f"Tool description: {tool.description}\n"
            f"Respond with JSON matching the schema. "
            f"Do not include any text outside the JSON."
        )

    @staticmethod
    def _append_missing_tool_feedback(
        prompt: str, tool: ToolDefinition,
    ) -> str:
        return (
            f"{prompt}\n\n"
            f"[System feedback]\n"
            f"Your previous response did not provide structured output "
            f"for the required tool \"{tool.name}\". "
            f"You MUST respond with valid JSON matching the schema."
        )

    @staticmethod
    def _append_validation_feedback(
        prompt: str, errors: dict[str, list[str]],
    ) -> str:
        lines = ["[System feedback]", "Schema validation errors in your previous response:"]
        for tool_name, tool_errors in sorted(errors.items()):
            for error in tool_errors:
                lines.append(f"- {tool_name}: {error}")
        lines.append("Please respond again with corrected values.")
        return f"{prompt}\n\n" + "\n".join(lines)

    def _validate_tool_calls(
        self,
        tool_calls: list[ToolCall],
        options: CompletionOptions,
    ) -> dict[str, list[str]]:
        schema_by_name = {tool.name: tool.input_schema for tool in options.tools}
        all_errors: dict[str, list[str]] = {}
        for tc in tool_calls:
            errors: list[str] = []
            schema = schema_by_name.get(tc.name)
            if schema:
                errors.extend(validate_tool_input(tc.input, schema))
            for validator in options.tool_input_validators:
                errors.extend(validator(tc.name, tc.input))
            if errors:
                all_errors[tc.name] = errors
        return all_errors

    # ------------------------------------------------------------------
    # CLI execution
    # ------------------------------------------------------------------

    def _build_cli_args(
        self,
        system: str | None,
        options: CompletionOptions,
        forced_tool: ToolDefinition | None,
    ) -> list[str]:
        args = [
            self._claude_path,
            "-p",
            "--output-format", "json",
            "--no-session-persistence",
            "--tools", "",
        ]

        if system:
            args.extend(["--system-prompt", system])

        model = self._map_model(options.model)
        if model:
            args.extend(["--model", model])

        if forced_tool:
            args.extend(["--json-schema", json.dumps(forced_tool.input_schema)])

        max_budget = os.environ.get("OSOJI_CLAUDE_CODE_MAX_BUDGET")
        if max_budget:
            args.extend(["--max-budget-usd", max_budget])

        return args

    @staticmethod
    def _map_model(model: str) -> str:
        stripped = model.strip()
        for prefix in ("anthropic/", "claude-code/"):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):]
        return stripped

    async def _execute_cli(
        self,
        args: list[str],
        prompt: str,
    ) -> dict[str, Any]:
        timeout = int(os.environ.get("OSOJI_LLM_TIMEOUT", _DEFAULT_LLM_TIMEOUT))

        # Strip ANTHROPIC_API_KEY so the CLI uses OAuth subscription auth
        # instead of burning API credits.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=timeout,
            )
        except (asyncio.TimeoutError, TimeoutError):
            proc.kill()
            await proc.wait()
            raise TimeoutError(
                f"Claude Code CLI timed out after {timeout}s. "
                f"Set OSOJI_LLM_TIMEOUT to a higher value (e.g. 1800)."
            )

        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
        stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""

        if proc.returncode != 0:
            # Claude Code with --output-format json may put error info in
            # stdout rather than stderr.  Extract it so callers see the real
            # error message instead of an empty string.
            error_detail = stderr_text
            if not error_detail.strip() and stdout_text.strip():
                try:
                    data = json.loads(stdout_text)
                    error_detail = data.get("result", stdout_text[:500])
                except json.JSONDecodeError:
                    error_detail = stdout_text[:500]
            raise ClaudeCodeCLIError(
                exit_code=proc.returncode or 1,
                stderr=error_detail,
                command=args,
            )
        try:
            data = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Claude Code CLI returned invalid JSON: {exc}\n"
                f"Raw output: {stdout_text[:500]}"
            ) from exc

        if data.get("is_error"):
            raise ClaudeCodeCLIError(
                exit_code=1,
                stderr=data.get("result", "Unknown error"),
                command=args,
            )

        return data

    async def _execute_and_parse(
        self,
        prompt: str,
        system: str | None,
        options: CompletionOptions,
        forced_tool: ToolDefinition | None,
    ) -> CompletionResult:
        args = self._build_cli_args(system, options, forced_tool)
        data = await self._execute_cli(args, prompt)
        return self._parse_response(data, forced_tool)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(
        data: dict[str, Any],
        forced_tool: ToolDefinition | None,
    ) -> CompletionResult:
        input_tokens = 0
        output_tokens = 0
        model_name = ""
        for model, usage in (data.get("modelUsage") or {}).items():
            if isinstance(usage, dict):
                input_tokens += usage.get("inputTokens", 0)
                output_tokens += usage.get("outputTokens", 0)
            if not model_name:
                model_name = model

        structured_output = data.get("structured_output")
        content = data.get("result")

        tool_calls: list[ToolCall] = []
        if forced_tool and structured_output is not None:
            tool_input = structured_output if isinstance(structured_output, dict) else {}
            tool_calls.append(
                ToolCall(
                    id=f"cc_{uuid4().hex[:12]}",
                    name=forced_tool.name,
                    input=tool_input,
                )
            )

        return CompletionResult(
            content=content if not tool_calls else None,
            tool_calls=tool_calls,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model_name or "claude-code",
            stop_reason="end_turn",
        )
