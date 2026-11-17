from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import gate, passwords, sessions  # noqa: E402


class WebSocketProxy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secret = b"w" * 32
        passwords.write_hash(self.root / "passwd", "test-password")
        self.closed = asyncio.Event()
        self.requests = []
        self.close_first = False
        self.protocols = ["echo"]

    async def connect(self, token=None, protocols=True):
        async def handler(ws):
            self.requests.append(ws.request)
            try:
                if self.close_first:
                    await ws.send("last-message")
                    return
                async for message in ws:
                    await ws.send(message)
            finally:
                self.closed.set()

        server = await self.enterAsyncContext(websockets.serve(
            handler, "127.0.0.1", 0, subprotocols=self.protocols,
        ))
        port = server.sockets[0].getsockname()[1]
        app = gate.build_app(
            data_dir=self.root, upstream_host="127.0.0.1", upstream_port=port, secret=self.secret,
        )
        await self.enterAsyncContext(app.router.lifespan_context(app))
        if token is None:
            key = sessions.password_key(self.secret, passwords.read_hash(self.root / "passwd"))
            token = sessions.issue(key)
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        headers = [
            (b"host", b"test.local"), (b"origin", b"http://test.local"),
            (b"connection", b"upgrade"), (b"upgrade", b"websocket"),
            (b"sec-websocket-key", b"dGhlIHNhbXBsZSBub25jZQ=="),
            (b"sec-websocket-version", b"13"),
            (b"cookie", f"styx_session={token}; hermes=kept".encode()),
        ]
        if protocols:
            headers.append((b"sec-websocket-protocol", b"echo, unused"))
        scope = {
            "type": "websocket", "asgi": {"version": "3.0", "spec_version": "2.5"},
            "scheme": "ws", "path": "/echo", "raw_path": b"/echo", "query_string": b"",
            "headers": headers, "subprotocols": ["echo", "unused"] if protocols else [],
            "client": ("127.0.0.1", 12345), "server": ("test.local", 80),
        }
        await self.incoming.put({"type": "websocket.connect"})
        self.task = asyncio.create_task(app(scope, self.incoming.get, self.outgoing.put))
        self.addAsyncCleanup(self.finish)
        self.port = port
        return await self.receive()

    async def receive(self):
        return await asyncio.wait_for(self.outgoing.get(), timeout=2)

    async def finish(self):
        if not self.task.done():
            self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def test_real_handshake_text_binary_and_client_disconnect(self):
        message = await self.connect()
        self.assertEqual(message["type"], "websocket.accept")
        self.assertEqual(message["subprotocol"], "echo")
        received = self.requests[0].headers
        self.assertEqual(len(received.get_all("Host")), 1)
        self.assertEqual(len(received.get_all("Sec-WebSocket-Key")), 1)
        self.assertEqual(received["Origin"], f"http://127.0.0.1:{self.port}")
        self.assertEqual(received["Cookie"], "hermes=kept")
        for kind, data in [("text", "hello"), ("bytes", b"\x00\x01")]:
            await self.incoming.put({"type": "websocket.receive", kind: data})
            echo = await self.receive()
            self.assertEqual(echo[kind], data)
        await self.incoming.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(self.task, timeout=2)
        await asyncio.wait_for(self.closed.wait(), timeout=2)

    async def test_upstream_disconnect_cancels_waiting_client_relay(self):
        self.close_first = True
        self.assertEqual((await self.connect())["type"], "websocket.accept")
        self.assertEqual((await self.receive())["text"], "last-message")
        self.assertEqual((await self.receive())["type"], "websocket.close")
        await asyncio.wait_for(self.task, timeout=2)

    async def test_password_change_closes_an_existing_websocket(self):
        with patch.object(gate, "_SESSION_CHECK_INTERVAL", 0.01):
            self.assertEqual((await self.connect())["type"], "websocket.accept")
            passwords.write_hash(self.root / "passwd", "replacement")
            closed = await self.receive()
            self.assertEqual(closed["type"], "websocket.close")
            self.assertEqual(closed["code"], 4401)
            await asyncio.wait_for(self.task, timeout=2)
            await asyncio.wait_for(self.closed.wait(), timeout=2)

    async def test_invalid_session_never_connects_upstream(self):
        self.assertEqual((await self.connect(token="invalid"))["code"], 4401)
        await asyncio.wait_for(self.task, timeout=2)
        self.assertFalse(self.requests)

    async def test_does_not_invent_an_upstream_subprotocol(self):
        self.protocols = None
        accepted = await self.connect()
        self.assertEqual(accepted["type"], "websocket.accept")
        self.assertIsNone(accepted["subprotocol"])
