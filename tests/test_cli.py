from __future__ import annotations

import argparse
import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import cli  # noqa: E402


class CliCommands(unittest.TestCase):
    def setUp(self):
        self.parser = argparse.ArgumentParser(prog="hermes styx")
        cli.register_cli(self.parser)

    def test_qr_command_is_not_advertised(self):
        self.assertNotIn("qr", self.parser.format_help())

    def test_qr_command_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                self.parser.parse_args(["qr"])
        self.assertEqual(error.exception.code, 2)

    def test_other_commands_remain_available(self):
        for name in ("setup", "status", "start", "stop", "url", "passwd", "client-auth", "doctor", "webapp"):
            with self.subTest(command=name):
                args = self.parser.parse_args([name])
                self.assertEqual(args.styx_command, name)
                self.assertIs(args.func, cli.styx_command)

    def test_webapp_mode_selection(self):
        self.assertEqual(self.parser.parse_args(["webapp"]).mode, "status")
        self.assertEqual(self.parser.parse_args(["webapp", "fast"]).mode, "fast")
        self.assertEqual(self.parser.parse_args(["webapp", "hermes"]).mode, "hermes")
