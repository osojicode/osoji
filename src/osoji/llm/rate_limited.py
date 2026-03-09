"""LLM provider wrapper that enforces proactive rate limiting."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import anthropic
import litellm

from ..rate_limiter import RateLimiter
from .base import LLMProvider
from .tokens import TokenCounter, estimate_tokens_offline
from .types import CompletionOptions, CompletionResult, Message, RateLimitMetadata

_MAX_RATE_LIMIT_RETRIES = 3


class RateLimitedProvider(LLMProvider):
    """Wrap an LLM provider with proactive RPM/TPM reservation tracking."""

    def __init__(
        self,
        provider: LLMProvider,
        rate_limiter: RateLimiter,
        *,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self._provider = provider
        self._rate_limiter = rate_limiter
        self._token_counter = token_counter

    @property
    def name(self) -> str:
        return self._provider.name

    async def complete(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> CompletionResult:
        reservation_key = options.reservation_key or "default"
        retry_count = 0

        while True:
            estimated_input_tokens = await self._estimate_input_tokens(
                messages,
                system,
                options,
            )
            reserved_input_tokens = (
                math.ceil(estimated_input_tokens * self._rate_limiter.input_safety_multiplier)
                if estimated_input_tokens > 0
                else 0
            )
            ticket = await self._rate_limiter.acquire(
                reservation_key=reservation_key,
                estimated_input_tokens=reserved_input_tokens,
                reserved_output_tokens=options.reserved_output_tokens,
                max_output_tokens=options.max_tokens,
            )

            try:
                result = await self._provider.complete(messages, system, options)
            except Exception as exc:
                if not self._is_retryable_error(exc):
                    await self._rate_limiter.finalize_failure(ticket, is_rate_limit=False)
                    raise
                retry_after = self._extract_retry_after(exc) or min(30.0, float(2 ** retry_count))
                await self._rate_limiter.finalize_failure(
                    ticket,
                    is_rate_limit=True,
                    retry_after=retry_after,
                )
                if retry_count >= _MAX_RATE_LIMIT_RETRIES:
                    raise
                retry_count += 1
                continue

            stats = await self._rate_limiter.finalize_success(
                ticket,
                actual_input_tokens=result.input_tokens,
                actual_output_tokens=result.output_tokens,
            )
            result.rate_limit = RateLimitMetadata(
                reservation_key=reservation_key,
                reserved_input_tokens=ticket.reserved_input_tokens,
                reserved_output_tokens=ticket.reserved_output_tokens,
                actual_input_tokens=result.input_tokens,
                actual_output_tokens=result.output_tokens,
                retry_count=retry_count,
                input_headroom_pct=stats.input_headroom_pct,
                output_headroom_pct=stats.output_headroom_pct,
            )
            return result

    async def close(self) -> None:
        await self._provider.close()
        if self._token_counter is not None:
            await self._token_counter.close()

    def get_rate_limit_summary(self) -> str:
        return self._rate_limiter.get_summary()

    async def _estimate_input_tokens(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> int:
        if options.estimated_input_tokens is not None:
            return max(0, options.estimated_input_tokens)

        if self._token_counter is not None:
            try:
                return max(
                    0,
                    await self._token_counter.count_tokens_async(
                        messages,
                        system=system,
                        model=options.model,
                    ),
                )
            except Exception:
                pass

        parts: list[str] = []
        if system:
            parts.append(system)

        for message in messages:
            parts.append(str(message.role.value))
            if isinstance(message.content, str):
                parts.append(message.content)
            else:
                parts.append(str(message.content))

        if options.tools:
            parts.extend(tool.name for tool in options.tools)
            parts.extend(tool.description for tool in options.tools)
            parts.extend(str(tool.input_schema) for tool in options.tools)

        if options.tool_choice:
            parts.append(str(options.tool_choice))

        return estimate_tokens_offline("\n".join(parts))

    def _is_retryable_error(self, exc: BaseException) -> bool:
        rate_limit_error = getattr(litellm, "RateLimitError", None)
        api_connection_error = getattr(litellm, "APIConnectionError", None)
        api_error = getattr(litellm, "APIError", None)
        internal_server_error = getattr(litellm, "InternalServerError", None)

        if isinstance(rate_limit_error, type) and isinstance(exc, rate_limit_error):
            return True
        if isinstance(api_connection_error, type) and isinstance(exc, api_connection_error):
            return True
        retryable_api_errors = tuple(
            error_type
            for error_type in (api_error, internal_server_error)
            if isinstance(error_type, type)
        )
        if retryable_api_errors and isinstance(exc, retryable_api_errors):
            status_code = self._status_code(exc)
            return status_code in {500, 502, 503, 504, 529}

        if self.name == "anthropic":
            names = (
                "RateLimitError",
                "ServiceUnavailableError",
                "OverloadedError",
                "InternalServerError",
            )
            for name in names:
                error_type = getattr(anthropic, name, None)
                if isinstance(error_type, type) and isinstance(exc, error_type):
                    return True

        return False

    def _extract_retry_after(self, exc: BaseException) -> float | None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is None:
            return None

        retry_after_ms = headers.get("retry-after-ms")
        if retry_after_ms:
            try:
                return max(0.0, float(retry_after_ms) / 1000.0)
            except ValueError:
                pass

        retry_after = headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    retry_time = parsedate_to_datetime(retry_after)
                except (TypeError, ValueError):
                    return None
                if retry_time.tzinfo is None:
                    retry_time = retry_time.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_time - datetime.now(timezone.utc)).total_seconds())

        return None

    def _status_code(self, exc: BaseException) -> int | None:
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        return None
