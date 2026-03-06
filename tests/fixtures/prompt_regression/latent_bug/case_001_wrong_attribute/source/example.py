"""Example module demonstrating a latent bug: wrong attribute access."""

from dataclasses import dataclass


@dataclass
class CompletionResult:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    stop_reason: str = ""


def record_token_usage(result: CompletionResult) -> dict:
    """Record token usage from a completion result."""
    return {
        "input": result.usage.get("input_tokens", 0),
        "output": result.usage.get("output_tokens", 0),
    }
