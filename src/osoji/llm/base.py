"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod

from .types import Message, CompletionOptions, CompletionResult


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    All LLM providers must implement this interface to be used
    with the shadow documentation generation system.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this provider."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        system: str | None,
        options: CompletionOptions,
    ) -> CompletionResult:
        """Generate a completion for the given messages.

        Args:
            messages: List of conversation messages
            system: Optional system prompt
            options: Completion options including model, tools, etc.

        Returns:
            CompletionResult with content, tool calls, and usage stats
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close any open connections.

        Should be called when the provider is no longer needed.
        """
        ...
