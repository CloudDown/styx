"""The terminal WebSocket, end to end through the gate (auth, routing, PTY pump)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

import httpx  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402
from test_gate_regressions import Chunks, Transport  # noqa: E402

from styx.backend import gate, passwords, sessions, terminal, tui_webapp  # noqa: E402


@unittest.skipUnless(os.name == "posix", "the terminal needs a POSIX pseudo-terminal")
class TuiSocket(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        passwords.write_hash(root / "passwd", "test-password")
        transport = Transport(lambda request: httpx.Response(200, stream=Chunks(b"ok")))
        real_client = httpx.AsyncClient
        patcher = patch.object(
            gate.httpx,
            "AsyncClient",
            side_effect=lambda **kw: real_client(transport=transport, **kw),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = gate.build_app(
            data_dir=root,
            upstream_host="127.0.0.1",
            upstream_port=9120,
            secret=b"x" * 32,
            webapp_handoff=False,
        )
        self.client = TestClient(self.app, follow_redirects=False)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def login(self):
        self.client.get("/login")
        csrf = self.client.cookies[sessions.CSRF_COOKIE]
        response = self.client.post("/login", data={"csrf": csrf, "password": "test-password"})
        self.assertEqual(response.status_code, 303)

    def test_the_socket_is_refused_before_the_login(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect(tui_webapp.SOCKET):
                pass

    def test_the_fixed_command_runs_in_a_pty_and_its_output_reaches_the_browser(self):
        self.login()
        code = "import sys; sys.stdout.write('pty-ok\\n'); sys.stdout.flush(); sys.stdin.read()"
        with patch.object(terminal, "command", return_value=[sys.executable, "-c", code]):
            with self.client.websocket_connect(tui_webapp.SOCKET) as socket:
                data = b""
                for _ in range(3):
                    data += socket.receive_bytes()
                    if b"pty-ok" in data:
                        break
                self.assertIn(b"pty-ok", data)
                # A resize frame is consumed as control, never written to the child.
                socket.send_text('{"type":"resize","cols":120,"rows":40}')
                # Ask the gate to hang up and wait for its close frame. Starlette's
                # TestClient cancels the session scope on exit; without this wait a
                # handler still unwinding can surface CancelledError on macOS.
                socket.close()
                with self.assertRaises(WebSocketDisconnect):
                    socket.receive_text()

    def test_terminal_start_failure_is_reported_and_the_socket_closed(self):
        self.login()
        with (
            patch.object(terminal, "command", return_value=[sys.executable, "-c", "pass"]),
            patch.object(terminal, "Terminal", side_effect=OSError("no pty")),
        ):
            with self.client.websocket_connect(tui_webapp.SOCKET) as socket:
                self.assertIn("Could not start the terminal", socket.receive_text())
                with self.assertRaises(WebSocketDisconnect):
                    socket.receive_text()

    def test_unknown_assets_are_404_and_the_vendor_files_are_cached(self):
        self.login()
        self.assertEqual(self.client.get(tui_webapp.TUI + "/nope.js").status_code, 404)
        asset = self.client.get(tui_webapp.TUI + "/xterm.css")
        self.assertEqual(asset.status_code, 200)
        self.assertIn("immutable", asset.headers["cache-control"])
