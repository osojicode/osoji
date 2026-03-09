"""Async helpers shared across high-fanout analysis flows."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

MAX_PENDING_TASKS = 256


async def gather_with_buffer(
    factories: Sequence[Callable[[], Awaitable[T]]],
    *,
    max_pending: int = MAX_PENDING_TASKS,
    return_exceptions: bool = False,
) -> list[T | Exception]:
    """Run awaitable factories while capping the number of pending tasks."""

    if max_pending <= 0:
        raise ValueError("max_pending must be positive")

    results: list[T | Exception | None] = [None] * len(factories)
    pending: dict[asyncio.Task[T], int] = {}
    next_index = 0

    async def start_one(index: int) -> T:
        return await factories[index]()

    while next_index < len(factories) or pending:
        while next_index < len(factories) and len(pending) < max_pending:
            task = asyncio.create_task(start_one(next_index))
            pending[task] = next_index
            next_index += 1

        if not pending:
            break

        done, _ = await asyncio.wait(pending.keys(), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            index = pending.pop(task)
            try:
                results[index] = await task
            except Exception as exc:
                if not return_exceptions:
                    for pending_task in pending:
                        pending_task.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    raise
                results[index] = exc

    return [result for result in results if result is not None]
