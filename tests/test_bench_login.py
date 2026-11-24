"""Pure helpers of the optional Tor login benchmark."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bench_login_tor.py"
_spec = importlib.util.spec_from_file_location("bench_login_tor", _SCRIPT)
bench = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(bench)


class BenchLogin(unittest.TestCase):
    def test_parses_the_csrf_and_the_webp_or_avif_fallback(self):
        html = '<input type="hidden" name="csrf" value="abc123">'
        html += '<picture><img src="/_styx/login-background-wide-1280-deadbeef.webp"></picture>'
        self.assertEqual(bench.parse_csrf(html), "abc123")
        self.assertEqual(
            bench.parse_painting_url(html), "/_styx/login-background-wide-1280-deadbeef.webp"
        )
        avif = (
            '<source type="image/avif" srcset="/_styx/login-background-wide-1280-cafe.avif 1280w">'
            + html
        )
        self.assertEqual(bench.parse_avif_url(avif), "/_styx/login-background-wide-1280-cafe.avif")
        with self.assertRaises(ValueError):
            bench.parse_avif_url(html)
        for broken in ("<html></html>", '<img src="/logo.png">'):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    bench.parse_csrf(broken)
                with self.assertRaises(ValueError):
                    bench.parse_painting_url(broken)
                with self.assertRaises(ValueError):
                    bench.parse_avif_url(broken)

    def test_summarizes_samples(self):
        self.assertEqual(bench.summarize([2.0, 4.0, 9.0]), {"min": 2.0, "median": 4.0, "max": 9.0})
        with self.assertRaises(ValueError):
            bench.summarize([])


if __name__ == "__main__":
    unittest.main()
