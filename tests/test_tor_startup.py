from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import types
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import tor_supervisor as tor  # noqa: E402


class TorStartup(unittest.TestCase):
    def test_windows_scoop_discovery_uses_real_tor_not_the_shim(self):
        with tempfile.TemporaryDirectory() as raw:
            executable = Path(raw) / "apps/tor/current/tor/tor.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch.dict(os.environ, {"SCOOP": raw, "STYX_TOR_BINARY": ""}):
                with patch.object(tor, "sys", types.SimpleNamespace(platform="win32")):
                    with patch.object(tor.shutil, "which", return_value="scoop-shim.exe"):
                        self.assertEqual(tor.tor_binary(), str(executable.resolve()))

    def test_logging_uses_redirected_stdout_not_a_quoted_filename(self):
        with tempfile.TemporaryDirectory(prefix="styx with spaces ") as raw:
            text = tor.render_torrc(data_dir=Path(raw), gate_port=9130, client_auth=False)
        self.assertIn("Log notice stdout\n", text)
        self.assertNotIn("Log notice file", text)

    def test_tor_inherits_only_allowlisted_environment_variables(self):
        allowed = {"PATH": "test-path", "HOME": "test-home", "SYSTEMROOT": "test-windows",
                   "TEMP": "test-temp", "TMP": "test-tmp", "TMPDIR": "test-tmpdir"}
        parent = {**allowed, "OPENAI_API_KEY": "test-secret", "HERMES_HOME": "test-profile"}
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with (
                patch.dict(os.environ, parent, clear=True),
                patch.object(tor, "tor_binary", return_value="test-tor"),
                patch.object(tor, "write_torrc", return_value=root / "torrc"),
                patch.object(tor.subprocess, "Popen") as spawn,
                patch.object(tor, "write_pid"),
            ):
                tor.start_tor(root, 9130)
        self.assertEqual(spawn.call_args.kwargs.get("env"), allowed)

    def test_dead_child_reports_exit_and_log_instead_of_pid_timeout(self):
        process = Mock(returncode=1)
        process.poll.return_value = 1
        with tempfile.TemporaryDirectory() as raw:
            with patch.object(tor, "_process_info") as inspect:
                with self.assertRaisesRegex(tor.TorError, r"tor exited.*exit 1.*tor.log"):
                    tor.write_pid(Path(raw) / "tor.pid", 12345, process=process)
            inspect.assert_not_called()

    @unittest.skipUnless(shutil.which("tor"), "Real Tor optional; no download in tests")
    def test_real_tor_starts_with_spaces_and_network_disabled(self):
        with tempfile.TemporaryDirectory(prefix="styx offline Tor ") as raw:
            root = Path(raw)
            (root / "tor").mkdir(mode=0o700)
            original = tor.render_torrc
            def offline(**kwargs):
                return original(**kwargs) + "DisableNetwork 1\n"
            with patch.object(tor, "render_torrc", side_effect=offline):
                process = tor.start_tor(root, 9130)
            try:
                # A syntactic --verify-config alone does NOT open Tor's logs
                # and did not catch the regression. Exercise the actual daemon.
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.5)
                self.assertEqual(tor.read_pid(root / "tor.pid"), process.pid)
                self.assertTrue((root / "logs/tor.log").is_file())
                self.assertNotIn("Failed to init Log", (root / "logs/tor.log").read_text(errors="replace"))
            finally:
                tor.stop_pid(root / "tor.pid", name="tor")
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=5)
