"""Blocking work off the loop must not free its capacity slot early."""

from __future__ import annotations

import asyncio
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend.offload import run_in_thread  # noqa: E402


class Offload(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_blocking_result(self):
        def work(value):
            return value * 2

        self.assertEqual(await run_in_thread(work, 21), 42)

    async def test_cancelled_caller_waits_for_the_thread_before_reraising(self):
        started = threading.Event()
        release = threading.Event()

        def slow():
            started.set()
            release.wait(5)
            return "finished"

        task = asyncio.create_task(run_in_thread(slow))
        while not started.is_set():
            await asyncio.sleep(0.005)
        task.cancel()
        await asyncio.sleep(0.05)
        self.assertFalse(task.done(), "the slot would be released too early")
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
