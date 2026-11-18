from __future__ import annotations

import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend.asset_transfer import accepts_gzip, compressible_asset, gzip_headers  # noqa: E402


class AssetTransfer(unittest.TestCase):
    def test_encoding_negotiation_respects_opt_out_and_wildcards(self):
        for value in ("gzip", "br, gzip", "*;q=0.5", "GZip; Q=1", "gzip;q=0.1"):
            with self.subTest(value=value):
                self.assertTrue(accepts_gzip(value))
        for value in ("", "br", "gzip;q=0", "*;q=1, gzip;q=0", "gzip;q=oops", "gzip;q=nan"):
            with self.subTest(value=value):
                self.assertFalse(accepts_gzip(value))

    def eligible(self, *, path="/assets/main-123abcXY.js", method="GET", status=200,
                 request_headers=None, response_headers=None):
        req = httpx.Request(method, "http://test.local" + path, headers={
            "accept-encoding": "gzip", **(request_headers or {}),
        })
        upstream = httpx.Response(status, headers={
            "content-type": "text/javascript; charset=utf-8",
            "content-length": "3400000",
            "cache-control": "public, max-age=31536000, immutable",
            **(response_headers or {}),
        })
        return compressible_asset(req, upstream)

    def test_only_explicitly_public_immutable_hashed_scripts_and_styles(self):
        self.assertTrue(self.eligible())
        self.assertTrue(self.eligible(path="/assets/main-123abcXY.css",
                                      response_headers={"content-type": "text/css"}))
        for options in (
            {"path": "/api/profiles"}, {"path": "/"}, {"path": "/webapp/window-session"},
            {"path": "/assets/main.js"}, {"path": "/assets/data-123abcXY.json"},
            {"method": "HEAD"}, {"method": "POST"}, {"status": 304}, {"status": 403},
            {"request_headers": {"accept-encoding": "gzip;q=0"}},
            {"request_headers": {"range": "bytes=0-99"}},
            {"request_headers": {"if-range": '"abc"'}},
            {"request_headers": {"cache-control": "no-transform"}},
            {"response_headers": {"content-encoding": "br"}},
            {"response_headers": {"content-range": "bytes 0-99/1000"}},
            {"response_headers": {"set-cookie": "private=value"}},
            {"response_headers": {"vary": "Cookie"}},
            {"response_headers": {"vary": "*"}},
            {"response_headers": {"content-type": "text/html"}},
            {"response_headers": {"cache-control": "no-store"}},
            {"response_headers": {"cache-control": "private, immutable"}},
            {"response_headers": {"cache-control": "public, immutable, no-transform"}},
            {"response_headers": {"content-length": "oops"}},
            {"response_headers": {"content-length": "500"}},
        ):
            with self.subTest(options=options):
                self.assertFalse(self.eligible(**options))

    def test_transformed_headers_do_not_claim_original_byte_length_or_digest(self):
        result = gzip_headers([
            (b"etag", b'"original"'), (b"content-length", b"1234"),
            (b"accept-ranges", b"bytes"), (b"content-digest", b"old"),
            (b"cache-control", b"public, immutable"), (b"vary", b"Origin"),
        ])
        self.assertIn((b"etag", b'W/"original"'), result)
        self.assertIn((b"content-encoding", b"gzip"), result)
        self.assertIn((b"vary", b"Origin"), result)
        self.assertIn((b"vary", b"Accept-Encoding"), result)
        self.assertNotIn(b"content-length", dict(result))
        self.assertNotIn(b"accept-ranges", dict(result))
        self.assertNotIn(b"content-digest", dict(result))
