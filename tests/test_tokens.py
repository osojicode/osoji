"""Tests for the bounded LRU cache in TokenCounter.count_text_async."""

import pytest

from osoji.llm.tokens import TokenCounter


def _counter() -> TokenCounter:
    # Non-Anthropic provider routes to the offline estimator: no network.
    return TokenCounter(provider="openai", default_model="gpt-4o")


def _key_for(counter: TokenCounter, text: str) -> str:
    return f"{counter.cache_key_prefix}:{counter._resolved_model(None)}:{hash(text)}"


@pytest.mark.asyncio
async def test_count_text_caches_repeat_counts():
    counter = _counter()
    text = "hello world " * 10

    first = await counter.count_text_async(text)
    second = await counter.count_text_async(text)

    assert first == second
    assert len(counter._cache) == 1


@pytest.mark.asyncio
async def test_cache_evicts_oldest_entry_past_the_bound(monkeypatch):
    monkeypatch.setattr("osoji.llm.tokens._MAX_CACHE_ENTRIES", 3)
    counter = _counter()

    texts = [f"text number {i} " * (i + 1) for i in range(4)]
    counts = [await counter.count_text_async(t) for t in texts]

    assert len(counter._cache) == 3
    assert _key_for(counter, texts[0]) not in counter._cache
    assert all(_key_for(counter, t) in counter._cache for t in texts[1:])
    # Evicted entries are recomputed correctly, not lost.
    assert await counter.count_text_async(texts[0]) == counts[0]


@pytest.mark.asyncio
async def test_cache_hit_refreshes_recency(monkeypatch):
    monkeypatch.setattr("osoji.llm.tokens._MAX_CACHE_ENTRIES", 2)
    counter = _counter()

    a, b, c = "alpha " * 3, "bravo " * 5, "charlie " * 7
    await counter.count_text_async(a)
    await counter.count_text_async(b)
    await counter.count_text_async(a)  # hit: a becomes most recent
    await counter.count_text_async(c)  # evicts b, not a

    assert _key_for(counter, a) in counter._cache
    assert _key_for(counter, b) not in counter._cache
    assert _key_for(counter, c) in counter._cache
