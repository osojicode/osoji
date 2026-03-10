"""Logging wrapper for LLM providers with token tracking."""

from collections import Counter
from dataclasses import dataclass, field

from .base import LLMProvider
from .types import Message, CompletionOptions, CompletionResult


@dataclass
class TokenStats:
    """Accumulated token usage statistics."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    request_count: int = 0
    length_stop_count: int = 0
    length_stop_examples: list[str] = field(default_factory=list)


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
        if result.stop_reason == "length":
            self._stats.length_stop_count += 1
            example = (
                f"{options.reservation_key} "
                f"(model={result.model or options.model}, max_tokens={options.max_tokens})"
            )
            self._stats.length_stop_examples.append(example)

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
            if result.stop_reason == "length":
                print(
                    "    [warn] stop_reason=length "
                    f"key={options.reservation_key} "
                    f"model={result.model or options.model} "
                    f"max_tokens={options.max_tokens}"
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
        if s.length_stop_count:
            counts = Counter(s.length_stop_examples)
            top_examples = ", ".join(
                f"{example} x{count}" if count > 1 else example
                for example, count in counts.most_common(3)
            )
            remainder = s.length_stop_count - sum(count for _, count in counts.most_common(3))
            warning = (
                f"Warnings: {s.length_stop_count} response(s) ended with stop_reason=length"
            )
            if top_examples:
                warning += f"\nLength stops: {top_examples}"
            if remainder > 0:
                warning += f", ... (+{remainder} more)"
            summary = f"{summary}\n{warning}"
        get_rate_limit_summary = getattr(self._provider, "get_rate_limit_summary", None)
        if callable(get_rate_limit_summary):
            rate_summary = get_rate_limit_summary()
            if rate_summary:
                return f"{summary}\n{rate_summary}"
        return summary
