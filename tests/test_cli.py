from __future__ import annotations

import argparse
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import cli, fast_webapp, paths, supervisor  # noqa: E402


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
        self.assertEqual(self.parser.parse_args(["webapp", "tui"]).mode, "tui")
        self.assertEqual(self.parser.parse_args(["webapp", "hermes"]).mode, "hermes")
        args = self.parser.parse_args(["webapp", "fast", "--source", "hermes-agent"])
        self.assertEqual(args.mode, "fast")
        self.assertEqual(str(args.source), "hermes-agent")

    def test_standalone_build_command_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            self.parser.parse_args(["webapp", "build-fast"])
        self.assertEqual(error.exception.code, 2)

    def test_fast_builds_before_selecting_and_reuses_the_result(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def build(root_dir, checkout):
                self.assertEqual(root_dir, root)
                self.assertEqual(checkout, Path.home() / ".hermes" / "hermes-agent")
                self.assertEqual(fast_webapp.read_mode(root), "hermes")
                generation = "a" * 24
                directory = root / "fast-builds" / generation
                directory.mkdir(parents=True)
                (directory / "index.html").write_text("<title>Hermes Fast</title>", encoding="utf-8")
                (root / "fast-build").write_text(generation, encoding="ascii")

            with patch.object(paths, "data_dir", return_value=root), \
                    patch.object(supervisor, "target_name", return_value="webapp"), \
                    patch.object(fast_webapp, "build", side_effect=build) as compile, \
                    contextlib.redirect_stdout(io.StringIO()):
                args = self.parser.parse_args(["webapp", "fast"])
                self.assertEqual(args.func(args), 0)
                self.assertEqual(fast_webapp.read_mode(root), "fast")
                self.assertEqual(args.func(args), 0)
                compile.assert_called_once()

    def test_fast_build_failure_preserves_the_previous_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fast_webapp.write_mode(root, "tui")
            with patch.object(paths, "data_dir", return_value=root), \
                    patch.object(supervisor, "target_name", return_value="webapp"), \
                    patch.object(fast_webapp, "build", side_effect=OSError("compile failed")) as compile, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                source = Path("another-checkout")
                self.assertEqual(cli._webapp("fast", source=source), 1)
                compile.assert_called_once_with(root, source)
                self.assertEqual(fast_webapp.read_mode(root), "tui")
