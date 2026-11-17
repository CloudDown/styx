from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import bootstrap, cli, passwords, paths, supervisor, tor_supervisor as tor  # noqa: E402


class Bootstrap(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {"STYX_TOR_BINARY": ""}))
        terminal = types.SimpleNamespace(platform="linux", stdin=Mock())
        terminal.stdin.isatty.return_value = True
        self.terminal = terminal
        self.enterContext(patch.object(bootstrap, "sys", terminal))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_installed_tor_never_prompts_or_runs_installer(self):
        with patch.object(tor, "tor_binary", return_value="/usr/bin/tor"):
            with patch.object(bootstrap, "install_command") as plan:
                self.assertEqual(bootstrap.ensure_tor(), "/usr/bin/tor")
        plan.assert_not_called()

    def test_missing_tor_never_installs_from_a_noninteractive_process(self):
        self.terminal.stdin.isatty.return_value = False
        with patch.object(tor, "tor_binary", return_value=None):
            with patch.object(bootstrap, "install_command") as plan:
                with self.assertRaisesRegex(bootstrap.SetupError, "interactive host"):
                    bootstrap.ensure_tor()
        plan.assert_not_called()

    def test_invalid_override_is_not_hidden_by_installing_another_tor(self):
        with patch.dict(os.environ, {"STYX_TOR_BINARY": "/invalid/tor"}):
            with patch.object(tor, "tor_binary", return_value=None):
                with patch.object(bootstrap, "install_command") as plan:
                    with self.assertRaisesRegex(bootstrap.SetupError, "STYX_TOR_BINARY is invalid"):
                        bootstrap.ensure_tor()
        plan.assert_not_called()

    def test_declining_confirmation_runs_nothing(self):
        with patch.object(tor, "tor_binary", return_value=None):
            with patch.object(bootstrap, "install_command", return_value=["sudo", "apt-get", "install", "tor"]):
                with patch("builtins.input", return_value=""):
                    with patch.object(bootstrap.subprocess, "run") as run:
                        with self.assertRaisesRegex(bootstrap.SetupError, "cancelled"):
                            bootstrap.ensure_tor()
        run.assert_not_called()

    def test_approved_install_rechecks_the_actual_executable(self):
        command = ["sudo", "apt-get", "install", "tor"]
        with patch.object(tor, "tor_binary", side_effect=[None, "/usr/bin/tor"]) as detect:
            with patch.object(bootstrap, "install_command", return_value=command):
                with patch("builtins.input", return_value="oui"):
                    with patch.object(bootstrap.subprocess, "run", return_value=Mock(returncode=0)) as run:
                        self.assertEqual(bootstrap.ensure_tor(), "/usr/bin/tor")
        run.assert_called_once_with(command, check=False)
        self.assertEqual(detect.call_count, 2)

    def test_failed_install_never_reports_ready(self):
        with patch.object(tor, "tor_binary", return_value=None):
            with patch.object(bootstrap, "install_command", return_value=["manager", "install", "tor"]):
                with patch("builtins.input", return_value="y"):
                    with patch.object(bootstrap.subprocess, "run", return_value=Mock(returncode=23)):
                        with self.assertRaisesRegex(bootstrap.SetupError, "exit 23"):
                            bootstrap.ensure_tor()

    def test_success_without_discoverable_tor_is_an_actionable_failure(self):
        with patch.object(tor, "tor_binary", return_value=None):
            with patch.object(bootstrap, "install_command", return_value=["manager", "install", "tor"]):
                with patch("builtins.input", return_value="y"):
                    with patch.object(bootstrap.subprocess, "run", return_value=Mock(returncode=0)):
                        with self.assertRaisesRegex(bootstrap.SetupError, "STYX_TOR_BINARY"):
                            bootstrap.ensure_tor()

    def test_linux_uses_distribution_manager_and_normal_sudo_prompt(self):
        commands = {"apt-get": "/usr/bin/apt-get", "pacman": "/usr/bin/pacman", "sudo": "/usr/bin/sudo"}
        with patch.object(bootstrap.platform, "freedesktop_os_release", return_value={"ID": "ubuntu", "ID_LIKE": "debian"}):
            with patch.object(bootstrap.shutil, "which", side_effect=commands.get):
                with patch.object(bootstrap.os, "geteuid", return_value=1000, create=True):
                    self.assertEqual(
                        bootstrap.install_command(),
                        ["/usr/bin/sudo", "/usr/bin/apt-get", "install", "tor"],
                    )

    def test_arch_install_never_performs_an_unrequested_system_upgrade(self):
        with patch.object(bootstrap.platform, "freedesktop_os_release", return_value={"ID": "arch"}):
            with patch.object(bootstrap.shutil, "which", return_value="/usr/bin/pacman"):
                with patch.object(bootstrap.os, "geteuid", return_value=0, create=True):
                    self.assertEqual(bootstrap.install_command(), ["/usr/bin/pacman", "-S", "--needed", "tor"])

    def test_macos_uses_existing_homebrew(self):
        self.terminal.platform = "darwin"
        with patch.object(bootstrap.shutil, "which", return_value="/opt/homebrew/bin/brew"):
            self.assertEqual(bootstrap.install_command(), ["/opt/homebrew/bin/brew", "install", "tor"])

    def test_windows_prefers_scoop_expert_bundle(self):
        self.terminal.platform = "win32"
        with patch.object(bootstrap.shutil, "which", side_effect=lambda name: {"scoop": "scoop.cmd", "winget": "winget.exe"}.get(name)):
            self.assertEqual(bootstrap.install_command(), ["scoop.cmd", "install", "tor"])

    def test_windows_winget_browser_install_keeps_agreements_explicit(self):
        self.terminal.platform = "win32"
        with patch.object(bootstrap.shutil, "which", side_effect=lambda name: "winget.exe" if name == "winget" else None):
            with patch.object(bootstrap.Path, "is_file", return_value=False):
                command = bootstrap.install_command()
        self.assertIn("TorProject.TorBrowser", command)
        self.assertIn("--interactive", command)
        self.assertFalse(any(arg.startswith("--accept-") for arg in command))


class SetupCLI(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))
        self.tor = self.enterContext(patch.object(bootstrap, "ensure_tor", return_value="/usr/bin/tor"))
        self.enterContext(patch.object(paths, "passwd_path", return_value=Path("not-read")))
        self.hash = self.enterContext(patch.object(passwords, "read_hash", return_value="existing-hash"))
        self.start = self.enterContext(patch.object(supervisor, "start", return_value={"url": None}))

    def test_setup_subcommand_runs_the_complete_start_path(self):
        parser = argparse.ArgumentParser()
        cli.register_cli(parser)
        args = parser.parse_args(["setup", "--client-auth", "--no-wait"])
        self.assertEqual(cli.styx_command(args), 0)
        self.tor.assert_called_once()
        self.start.assert_called_once_with(wait=False, client_auth=True)

    def test_missing_password_is_requested_interactively_without_overwriting_existing_password(self):
        self.hash.return_value = None
        with patch.object(cli.sys.stdin, "isatty", return_value=True):
            with patch.object(cli, "_passwd", return_value=0) as password:
                self.assertEqual(cli._start(client_auth=False, wait=True), 0)
        password.assert_called_once_with(None)
        self.start.assert_called_once()

    def test_noninteractive_start_with_missing_password_refuses_to_start(self):
        self.hash.return_value = None
        with patch.object(cli.sys.stdin, "isatty", return_value=False):
            self.assertEqual(cli._start(client_auth=False, wait=True), 1)
        self.start.assert_not_called()

    def test_setup_error_never_starts_the_onion_service(self):
        self.tor.side_effect = bootstrap.SetupError("cancelled")
        self.assertEqual(cli._start(client_auth=False, wait=True), 1)
        self.start.assert_not_called()
