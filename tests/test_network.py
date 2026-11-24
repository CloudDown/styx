from __future__ import annotations

import http.server
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend.network import upstream_health  # noqa: E402


class Health(unittest.TestCase):
    def setUp(self):
        self.code, self.body, self.location = 200, b"<!doctype html><title>Hermes</title>", None
        self.calls = 0
        test = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                test.calls += 1
                self.send_response(test.code)
                if test.location:
                    self.send_header("Location", test.location)
                self.end_headers()
                self.wfile.write(test.body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def health(self):
        return upstream_health("127.0.0.1", self.server.server_port)

    def test_healthy_interface(self):
        self.assertEqual(self.health(), (True, None))

    def test_open_port_with_missing_bundle_is_not_healthy(self):
        self.code = 404
        self.body = b"<title>Hermes is unavailable</title>The Webapp is not built"
        healthy, error = self.health()
        self.assertFalse(healthy)
        self.assertIn("missing or stale", error)

    def test_error_page_is_not_healthy_even_with_status_200(self):
        self.body = b"<title>Hermes is unavailable</title>"
        self.assertFalse(self.health()[0])

    def test_http_error_is_not_healthy(self):
        self.code = 503
        self.assertFalse(self.health()[0])

    def test_sign_in_redirect_is_accepted_but_never_followed(self):
        self.code, self.location = 303, "http://invalid.example/sign-in"
        self.assertTrue(self.health()[0])
        self.assertEqual(self.calls, 1)

    def test_non_loopback_is_refused(self):
        self.assertFalse(upstream_health("192.0.2.1", 9120)[0])
        self.assertEqual(self.calls, 0)
