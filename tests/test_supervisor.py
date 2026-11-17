from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx import passwords, paths, supervisor, tor_supervisor as tor  # noqa: E402
from styx.network import wait_port  # noqa: E402


class Supervisor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        passwords.write_hash(self.root / "passwd", "test-password")
        # Treat the identity as opaque; no test starts a real Tor instance.
        hs = paths.hidden_service_dir(self.root)
        (hs / "identity-sentinel").write_bytes(b"must survive stop and rollback")
        self.current = {
            "running": False, "onion": None, "gate_pid": None, "tor_pid": None,
            "gate_port": 9130, "upstream_host": "127.0.0.1", "upstream_port": 9120,
            "client_auth": False,
        }

    def mock_start(self):
        self.enterContext(patch.object(tor, "tor_binary", return_value="/usr/bin/tor"))
        self.enterContext(patch("styx.webapp_ensure.ensure_upstream", return_value=("127.0.0.1", 9120)))
        self.enterContext(patch.object(supervisor, "status", return_value=self.current))
        self.enterContext(patch.object(supervisor, "gate_port", return_value=9130))
        self.enterContext(patch.object(supervisor, "target_name", return_value="webapp"))
        self.enterContext(patch.object(supervisor, "port_open", return_value=False))
        self.ready = self.enterContext(patch.object(supervisor, "wait_port", return_value=True))
        self.spawn = self.enterContext(patch.object(supervisor, "_spawn_gate"))
        self.spawn.return_value.poll.return_value = None
        self.tor_start = self.enterContext(patch.object(tor, "start_tor"))
        self.hostname = self.enterContext(patch.object(tor, "wait_for_hostname", return_value=None))
        self.stop_pid = self.enterContext(patch.object(tor, "stop_pid"))

    def assert_cleaned(self):
        self.assertEqual([call.kwargs["name"] for call in self.stop_pid.call_args_list], ["tor", "gate"])
        self.assertEqual(
            (paths.hidden_service_dir(self.root) / "identity-sentinel").read_bytes(),
            b"must survive stop and rollback",
        )

    def test_tor_start_failure_rolls_back_both_services(self):
        self.mock_start()
        self.tor_start.side_effect = tor.TorError("tor startup failed")
        with self.assertRaisesRegex(supervisor.StyxError, "startup failed"):
            supervisor.start(data_dir=self.root)
        self.assert_cleaned()
        self.assertFalse(paths.state_path(self.root).exists())

    def test_gate_bind_failure_rolls_back_without_starting_tor(self):
        self.mock_start()
        self.ready.return_value = False
        with self.assertRaisesRegex(supervisor.StyxError, "did not bind"):
            supervisor.start(data_dir=self.root)
        self.tor_start.assert_not_called()
        self.assert_cleaned()

    def test_state_write_failure_rolls_back(self):
        self.mock_start()
        with patch.object(supervisor, "write_state", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(supervisor.StyxError, "disk full"):
                supervisor.start(data_dir=self.root)
        self.assert_cleaned()

    def test_no_wait_keeps_live_tor_when_hostname_is_not_ready(self):
        self.mock_start()
        self.hostname.side_effect = tor.TorStartupTimeout("still starting")
        supervisor.start(data_dir=self.root, wait=False)
        self.stop_pid.assert_not_called()
        self.assertIsNone(supervisor.read_state(self.root)["onion"])

    def test_no_wait_still_rolls_back_if_tor_exits(self):
        self.mock_start()
        self.hostname.side_effect = tor.TorError("tor exited")
        with self.assertRaisesRegex(supervisor.StyxError, "tor exited"):
            supervisor.start(data_dir=self.root, wait=False)
        self.assert_cleaned()

    def test_waiting_hostname_timeout_rolls_back(self):
        self.mock_start()
        self.hostname.side_effect = tor.TorStartupTimeout("timeout")
        with self.assertRaisesRegex(supervisor.StyxError, "timeout"):
            supervisor.start(data_dir=self.root)
        self.assert_cleaned()

    def test_occupied_gate_port_is_not_mistaken_for_our_gate(self):
        self.mock_start()
        with patch.object(supervisor, "port_open", return_value=True):
            with self.assertRaisesRegex(supervisor.StyxError, "occupied"):
                supervisor.start(data_dir=self.root)
        self.spawn.assert_not_called()
        self.stop_pid.assert_not_called()

    def test_start_and_stop_are_exclusive_even_across_threads(self):
        entered, release = threading.Event(), threading.Event()
        def starting(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(timeout=3))
            return {"running": True}
        with ThreadPoolExecutor(max_workers=1) as pool:
            with patch.object(supervisor, "_start_locked", side_effect=starting):
                with patch.object(supervisor, "_stop_locked") as stopping:
                    running = pool.submit(supervisor.start, data_dir=self.root)
                    try:
                        self.assertTrue(entered.wait(timeout=3))
                        with self.assertRaisesRegex(supervisor.StyxError, "in progress"):
                            supervisor.stop(data_dir=self.root)
                        stopping.assert_not_called()
                    finally:
                        release.set()
                    self.assertTrue(running.result(timeout=3)["running"])

    def test_stop_attempts_gate_cleanup_even_if_tor_stop_fails(self):
        with patch.object(tor, "stop_pid", side_effect=[tor.TorError("cannot stop tor"), None]) as stopping:
            with self.assertRaisesRegex(supervisor.StyxError, "cannot stop tor"):
                supervisor.stop(data_dir=self.root)
        self.assertEqual([c.kwargs["name"] for c in stopping.call_args_list], ["tor", "gate"])

    def test_pid_for_an_unrelated_process_is_never_signalled(self):
        pidfile = paths.gate_pid_path(self.root)
        pidfile.write_text(str(os.getpid()))
        with patch.object(tor.signal, "pidfd_send_signal") as signal:
            tor.stop_pid(pidfile, name="gate")
        signal.assert_not_called()
        self.assertFalse(pidfile.exists())

    def test_saved_birth_identity_must_match(self):
        pidfile = paths.gate_pid_path(self.root)
        saved = {"pid": 12345, "start_time": "100", "boot_id": "boot"}
        pidfile.write_text(json.dumps(saved))
        live = dict(saved, start_time="101")
        with patch.object(tor, "_process_info", return_value=live):
            self.assertIsNone(tor.read_pid(pidfile))
        with patch.object(tor, "_process_info", return_value=saved):
            self.assertEqual(tor.read_pid(pidfile), 12345)

    def test_pid_registration_waits_for_child_proc_identity(self):
        pidfile = paths.gate_pid_path(self.root)
        info = {"pid": 12345, "start_time": "100", "boot_id": "boot"}
        # /proc can be transiently unreadable/incomplete around exec.
        with patch.object(tor, "_process_info", side_effect=[None, info]):
            with patch.object(tor.time, "sleep"):
                tor.write_pid(pidfile, 12345)
        self.assertEqual(json.loads(pidfile.read_text()), info)

    def test_pid_registration_never_accepts_a_persistent_mismatch(self):
        pidfile = paths.gate_pid_path(self.root)
        with patch.object(tor, "_process_info", return_value=None):
            with patch.object(tor.time, "monotonic", side_effect=[0, 2]):
                with self.assertRaisesRegex(tor.TorError, "cannot identify"):
                    tor.write_pid(pidfile, 12345)
        self.assertFalse(pidfile.exists())

    def test_identity_is_rechecked_after_pinning_pid(self):
        pidfile = paths.gate_pid_path(self.root)
        pidfile.write_text("12345")
        with patch.object(tor, "read_pid", side_effect=[12345, None]):
            with patch.object(tor.os, "pidfd_open", return_value=123):
                with patch.object(tor.os, "close") as close:
                    with patch.object(tor.signal, "pidfd_send_signal") as signal:
                        tor.stop_pid(pidfile)
        close.assert_called_once_with(123)
        signal.assert_not_called()

    def test_real_gate_pid_can_be_stopped_without_touching_identity(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        proc = supervisor._spawn_gate(self.root, "127.0.0.1", 9120, port)
        try:
            self.assertTrue(wait_port("127.0.0.1", port, timeout=8))
            self.assertEqual(tor.read_pid(paths.gate_pid_path(self.root)), proc.pid)
            # Also check upgrade compatibility with old integer pidfiles.
            paths.gate_pid_path(self.root).write_text(str(proc.pid))
            self.assertEqual(tor.read_pid(paths.gate_pid_path(self.root)), proc.pid)
            tor.stop_pid(paths.gate_pid_path(self.root), name="gate")
            proc.wait(timeout=5)
            self.assertFalse(paths.gate_pid_path(self.root).exists())
            self.assertTrue((paths.hidden_service_dir(self.root) / "identity-sentinel").exists())
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)

    def test_dead_tor_is_not_hidden_by_an_old_hostname(self):
        paths.hostname_path(self.root).write_text("a" * 56 + ".onion")
        with patch.object(tor, "read_pid", return_value=None):
            with self.assertRaisesRegex(tor.TorError, "exited"):
                tor.wait_for_hostname(self.root)
