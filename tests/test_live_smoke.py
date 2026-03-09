"""Optional live smoke tests for non-Anthropic providers."""

import asyncio
import os

import pytest

from osoji.llm.factory import create_provider
from osoji.llm.types import CompletionOptions, Message, MessageRole, ToolDefinition

pytestmark = pytest.mark.live_smoke

TOOL_DEF = ToolDefinition(
    name="submit_answer",
    description="Submit a short answer.",
    input_schema={
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    },
)


async def _run_smoke(provider_name: str, model: str) -> None:
    provider = create_provider(provider_name)
    try:
        result = await provider.complete(
            messages=[
                Message(
                    role=MessageRole.USER,
                    content="Use the submit_answer tool and set answer to 'ok'.",
                )
            ],
            system="You must call the submit_answer tool exactly once.",
            options=CompletionOptions(
                model=model,
                max_tokens=128,
                tools=[TOOL_DEF],
                tool_choice={"type": "tool", "name": "submit_answer"},
            ),
        )
    finally:
        await provider.close()

    assert result.model
    assert result.input_tokens >= 0
    assert result.output_tokens >= 0
    assert result.tool_calls
    assert result.tool_calls[0].name == "submit_answer"


@pytest.mark.skipif(
    not (os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_LIVE_MODEL")),
    reason="requires OPENAI_API_KEY and OPENAI_LIVE_MODEL",
)
def test_openai_live_smoke():
    asyncio.run(_run_smoke("openai", os.environ["OPENAI_LIVE_MODEL"]))


@pytest.mark.skipif(
    not (os.getenv("GEMINI_API_KEY") and os.getenv("GEMINI_LIVE_MODEL")),
    reason="requires GEMINI_API_KEY and GEMINI_LIVE_MODEL",
)
def test_google_live_smoke():
    asyncio.run(_run_smoke("google", os.environ["GEMINI_LIVE_MODEL"]))


@pytest.mark.skipif(
    not (os.getenv("OPENROUTER_API_KEY") and os.getenv("OPENROUTER_LIVE_MODEL")),
    reason="requires OPENROUTER_API_KEY and OPENROUTER_LIVE_MODEL",
)
def test_openrouter_live_smoke():
    asyncio.run(_run_smoke("openrouter", os.environ["OPENROUTER_LIVE_MODEL"]))
