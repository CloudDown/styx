from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.headers import inbound_response_headers, outbound_headers, strip_styx_cookies  # noqa: E402
from styx.tor_supervisor import render_torrc  # noqa: E402


class ProxyAndTorrc(unittest.TestCase):
    def test_strips_styx_cookie_keeps_others(self):
        self.assertEqual(
            strip_styx_cookies("styx_session=abc; hermes=1; styx_csrf=x"),
            "hermes=1",
        )

    def test_outbound_host_is_loopback(self):
        headers = outbound_headers(
            {
                "Host": "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz234567.onion",
                "Origin": "http://abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz234567.onion",
                "Cookie": "styx_session=nope; other=1",
                "Accept": "text/html",
            },
            upstream_host="127.0.0.1",
            upstream_port=9120,
        )
        got = {k.lower(): v for k, v in headers}
        self.assertEqual(got["host"], "127.0.0.1:9120")
        self.assertEqual(got["origin"], "http://127.0.0.1:9120")
        self.assertNotIn("styx_session", got.get("cookie", ""))
        self.assertIn("other=1", got.get("cookie", ""))
        self.assertEqual(got["accept"], "text/html")

    def test_torrc_points_at_gate(self):
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            text = render_torrc(data_dir=tmp, gate_port=9130, client_auth=False)
            self.assertIn("SocksPort 0", text)
            self.assertIn("HiddenServiceVersion 3", text)
            self.assertIn("HiddenServicePort 80 127.0.0.1:9130", text)
            self.assertIn((tmp / "hidden_service").resolve().as_posix(), text)

    def test_torrc_quotes_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="styx space ") as raw:
            root = Path(raw)
            text = render_torrc(data_dir=root, gate_port=9130, client_auth=False)
            self.assertIn(f'DataDirectory "{(root / "tor").resolve().as_posix()}"', text)
            self.assertIn(f'HiddenServiceDir "{(root / "hidden_service").resolve().as_posix()}"', text)

    def test_connection_nominated_headers_are_removed_in_both_directions(self):
        incoming = [("Connection", "keep-alive, X-Private"), ("X-Private", "no"), ("Accept", "yes")]
        outgoing = outbound_headers(incoming, upstream_host="127.0.0.1", upstream_port=9120)
        self.assertNotIn("x-private", {k.lower() for k, v in outgoing})
        self.assertEqual(inbound_response_headers(incoming), [("Accept", "yes")])

    def test_response_preserves_encoding_length_and_duplicate_cookies(self):
        incoming = [
            ("Content-Encoding", "gzip"), ("Content-Length", "123"),
            ("Set-Cookie", "one=1"), ("Set-Cookie", "two=2"),
        ]
        self.assertEqual(inbound_response_headers(incoming), incoming)

    def test_websocket_headers_leave_negotiation_to_websockets(self):
        incoming = {
            "Host": "test.local", "Sec-WebSocket-Key": "key", "Sec-WebSocket-Version": "13",
            "Sec-WebSocket-Extensions": "permessage-deflate", "Sec-WebSocket-Protocol": "echo",
        }
        outgoing = outbound_headers(incoming, upstream_host="127.0.0.1", upstream_port=9120, websocket=True)
        self.assertEqual(outgoing, [("Origin", "http://127.0.0.1:9120")])


if __name__ == "__main__":
    unittest.main()
