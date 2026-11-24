"""Run blocking work off the gate event loop without losing its capacity slot.

Password hashing, login rendering and the Hermes launch subprocess all block.
An HTTP client can disappear at any moment, so the ASGI task may be cancelled
while the worker thread is still running. Releasing a bounded slot at that
point would let a cancellation storm queue unbounded scrypt or subprocess work.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


async def run_in_thread(func: Callable[..., T], *args: object) -> T:
    """Run ``func(*args)`` in a worker thread and wait for it, even if cancelled.

    A cancelled caller is re-raised only after the thread has actually
    returned, so the surrounding ``async with slots`` block keeps holding its
    slot for the whole blocking call.
    """
    work = asyncio.create_task(asyncio.to_thread(func, *args))
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(work)
            break
        except asyncio.CancelledError:
            if work.cancelled():
                raise
            cancelled = True
    if cancelled:
        raise asyncio.CancelledError
    return result
