"""The PTY behind the terminal interface. POSIX only: Windows has no equivalent here."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import terminal  # noqa: E402


@unittest.skipUnless(os.name == "posix", "pseudo-terminals are POSIX only")
class TerminalTests(unittest.IsolatedAsyncioTestCase):
    async def drain(self, session) -> bytes:
        data = b""
        while True:
            chunk = await asyncio.wait_for(session.reader.get(), timeout=10)
            if chunk is None:
                return data
            data += chunk

    async def test_a_child_sees_a_real_terminal_and_its_output_reaches_us(self):
        session = terminal.Terminal([sys.executable, "-c",
                                     "import sys; print(sys.stdout.isatty()); sys.stdout.flush()"])
        self.addCleanup(session.close)
        self.assertIn(b"True", await self.drain(session))

    async def test_the_pseudo_terminal_carries_the_requested_size(self):
        code = "import shutil, sys; print(shutil.get_terminal_size().columns); sys.stdout.flush()"
        session = terminal.Terminal([sys.executable, "-c", code], cols=111, rows=37)
        self.addCleanup(session.close)
        self.assertIn(b"111", await self.drain(session))

    async def test_input_reaches_the_child(self):
        code = ("import sys; line = sys.stdin.readline(); "
                "sys.stdout.write('got:' + line.strip()); sys.stdout.flush()")
        session = terminal.Terminal([sys.executable, "-c", code])
        self.addCleanup(session.close)
        session.write(b"ping\n")
        self.assertIn(b"got:ping", await self.drain(session))

    async def test_command_is_the_fixed_tui_invocation(self):
        found = terminal.command()
        if found is None:
            self.skipTest("no hermes launcher on PATH")
        self.assertEqual(found[-1], "--tui")
        self.assertTrue(os.path.isabs(found[0]))
