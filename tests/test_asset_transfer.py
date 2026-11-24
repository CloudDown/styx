from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from test_gate_regressions import Chunks  # noqa: E402

from styx.backend import asset_transfer as transfer  # noqa: E402
from styx.backend.asset_transfer import accepts_gzip, asset_encoding, encoding_headers  # noqa: E402


class AssetTransfer(unittest.IsolatedAsyncioTestCase):
    def test_encoding_negotiation_respects_opt_out_and_wildcards(self):
        for value in ("gzip", "br, gzip", "*;q=0.5", "GZip; Q=1", "gzip;q=0.1"):
            with self.subTest(value=value):
                self.assertTrue(accepts_gzip(value))
        for value in ("", "br", "gzip;q=0", "*;q=1, gzip;q=0", "gzip;q=oops", "gzip;q=nan"):
            with self.subTest(value=value):
                self.assertFalse(accepts_gzip(value))

    def eligible(
        self,
        *,
        path="/assets/main-123abcXY.js",
        method="GET",
        status=200,
        request_headers=None,
        response_headers=None,
        prefer_zstd=False,
    ):
        req = httpx.Request(
            method,
            "http://test.local" + path,
            headers={"accept-encoding": "gzip", **(request_headers or {})},
        )
        upstream = httpx.Response(
            status,
            headers={
                "content-type": "text/javascript; charset=utf-8",
                "content-length": "3400000",
                "cache-control": "public, max-age=31536000, immutable",
                **(response_headers or {}),
            },
        )
        return asset_encoding(req, upstream, prefer_zstd=prefer_zstd)

    def test_zstd_selected_only_when_supported_and_explicitly_preferred(self):
        with patch.object(transfer, "zstd", object()):
            for value, expected in (
                ("zstd, gzip", "zstd"),
                ("zstd;q=0.7, gzip", "gzip"),
                ("zstd;q=0, gzip;q=0", None),
                ("*", "gzip"),
            ):
                self.assertEqual(
                    self.eligible(request_headers={"accept-encoding": value}, prefer_zstd=True),
                    expected,
                )
            self.assertEqual(
                self.eligible(request_headers={"accept-encoding": "zstd, gzip"}), "gzip"
            )
            self.assertIsNone(
                self.eligible(
                    path="/api/profiles",
                    request_headers={"accept-encoding": "zstd"},
                    prefer_zstd=True,
                )
            )
        with patch.object(transfer, "zstd", None):
            self.assertEqual(
                self.eligible(request_headers={"accept-encoding": "zstd, gzip"}, prefer_zstd=True),
                "gzip",
            )

    @unittest.skipIf(transfer.zstd is None, "stdlib zstd requires Python 3.14")
    async def test_zstd_stream_round_trip(self):
        chunk = b"const data = ['official renderer'];\n" * 2000
        upstream = httpx.Response(200, stream=Chunks(chunk, chunk))
        encoded = b"".join([part async for part in transfer.compressed_stream(upstream, "zstd")])
        self.assertEqual(transfer.zstd.decompress(encoded), chunk * 2)
        self.assertLess(len(encoded), len(chunk))

    def test_only_explicitly_public_immutable_hashed_scripts_and_styles(self):
        self.assertTrue(self.eligible())
        self.assertTrue(
            self.eligible(
                path="/assets/main-123abcXY.css", response_headers={"content-type": "text/css"}
            )
        )
        for options in (
            {"path": "/api/profiles"},
            {"path": "/"},
            {"path": "/webapp/window-session"},
            {"path": "/assets/main.js"},
            {"path": "/assets/data-123abcXY.json"},
            {"method": "HEAD"},
            {"method": "POST"},
            {"status": 304},
            {"status": 403},
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
        result = encoding_headers(
            [
                (b"etag", b'"original"'),
                (b"content-length", b"1234"),
                (b"accept-ranges", b"bytes"),
                (b"content-digest", b"old"),
                (b"cache-control", b"public, immutable"),
                (b"vary", b"Origin"),
            ],
            "gzip",
        )
        self.assertIn((b"etag", b'W/"original"'), result)
        self.assertIn((b"content-encoding", b"gzip"), result)
        self.assertIn((b"vary", b"Origin"), result)
        self.assertIn((b"vary", b"Accept-Encoding"), result)
        self.assertNotIn(b"content-length", dict(result))
        self.assertNotIn(b"accept-ranges", dict(result))
        self.assertNotIn(b"content-digest", dict(result))
