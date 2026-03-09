"""Logging wrapper for LLM providers with token tracking."""

from dataclasses import dataclass

from .base import LLMProvider
from .types import Message, CompletionOptions, CompletionResult


@dataclass
class TokenStats:
    """Accumulated token usage statistics."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    request_count: int = 0


class LoggingProvider(LLMProvider):
    """Wrapper provider that tracks token usage and optionally logs requests.

    This provider wraps another provider and accumulates statistics
    about all requests made through it.
    """

    def __init__(self, provider: LLMProvider, verbose: bool = False) -> None:
        """Initialize the logging provider.

        Args:
            provider: The underlying provider to wrap
            verbose: If True, print request details to stdout
        """
        self._provider = provider
        self._stats = TokenStats()
        self._verbose = verbose

    @property
    def name(self) -> str:
        """Return the name of the wrapped provider."""
        return self._provider.name

    @property
    def stats(self) -> TokenStats:
        """Return the current token statistics."""
        return self._stats

    async def complete(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> CompletionResult:
        """Generate a completion and track token usage.

        Args:
            messages: List of conversation messages
            system: Optional system prompt
            options: Completion options

        Returns:
            CompletionResult from the underlying provider
        """
        result = await self._provider.complete(messages, system, options)

        # Update statistics
        self._stats.total_input_tokens += result.input_tokens
        self._stats.total_output_tokens += result.output_tokens
        self._stats.request_count += 1

        if self._verbose:
            extra = ""
            if result.rate_limit is not None:
                reserved = result.rate_limit
                extra = (
                    f" reserved={reserved.reserved_input_tokens:,}/{reserved.reserved_output_tokens:,}"
                    f" headroom={reserved.input_headroom_pct:.0f}%/{reserved.output_headroom_pct:.0f}%"
                )
                if reserved.retry_count:
                    extra += f" retries={reserved.retry_count}"
            print(
                f"    [tokens] in={result.input_tokens:,} out={result.output_tokens:,}{extra}"
            )

        return result

    async def close(self) -> None:
        """Close the underlying provider."""
        await self._provider.close()

    def get_token_summary(self) -> str:
        """Get a formatted summary of token usage.

        Returns:
            Human-readable summary string
        """
        s = self._stats
        total = s.total_input_tokens + s.total_output_tokens
        summary = (
            f"API calls: {s.request_count} | "
            f"Tokens: {total:,} (in: {s.total_input_tokens:,}, out: {s.total_output_tokens:,})"
        )
        get_rate_limit_summary = getattr(self._provider, "get_rate_limit_summary", None)
        if callable(get_rate_limit_summary):
            rate_summary = get_rate_limit_summary()
            if rate_summary:
                return f"{summary}\n{rate_summary}"
        return summary
