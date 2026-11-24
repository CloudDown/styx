from __future__ import annotations

import base64
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import login_page, sessions  # noqa: E402


class LoginAndSessions(unittest.TestCase):
    def test_login_is_minimal_and_has_no_network(self):
        html = login_page.render(error="x", csrf="token")
        self.assertIn("Styx", html)
        self.assertIn('name="password"', html)
        self.assertIn("csrf", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("fonts.google", html)
        self.assertNotIn("http://", html.replace("http://www.w3.org/2000/svg", ""))
        lowered = html.lower()
        self.assertIn("<svg", lowered)
        self.assertIn("backdrop-filter: blur(", html)
        self.assertNotIn("<footer", lowered)
        self.assertNotIn("<h1", lowered)
        image = Path(__file__).resolve().parents[1] / "assets/login/landscape-1600.webp"
        self.assertEqual(login_page.background_bytes(), image.read_bytes())
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        self.assertIn(f"/_styx/login-background-landscape-1600-{digest}.webp", html)
        self.assertEqual(login_page.background_etag(), f'"{digest}"')
        self.assertIn("<picture", html)
        self.assertIn('fetchpriority="high"', html)
        self.assertNotIn('rel="preload"', html)
        self.assertIn("autofocus", html)
        self.assertNotIn("data:image/jpeg;base64,", html)
        preview = html.split("data:image/webp;base64,", 1)[1].split('"', 1)[0]
        self.assertLess(len(base64.b64decode(preview)), 1024)
        self.assertLess(len(html.encode()), 7000)

    def test_backgrounds_are_bounded_local_crops_not_arbitrary_paths(self):
        root = Path(__file__).resolve().parents[1]
        original_size = (root / "assets/login-background.jpg").stat().st_size
        for variant in login_page.BACKGROUND_SIZES:
            image = login_page.background_bytes(variant)
            self.assertEqual(image[:4], b"RIFF")
            self.assertEqual(image[8:12], b"WEBP")
            self.assertLess(len(image), original_size // 3)
            self.assertIn(hashlib.sha256(image).hexdigest(), login_page.background_url(variant))
        self.assertLess(len(login_page.background_bytes("portrait-640")), 100_000)
        for variant in ("../passwd", "original", "portrait-99999"):
            with self.assertRaises(ValueError):
                login_page.background_bytes(variant)

    def test_mobile_layout_and_native_resolution_selection(self):
        html = login_page.render()
        self.assertIn('media="(max-width: 600px), (max-aspect-ratio: 3/5)"', html)
        self.assertIn('media="(max-aspect-ratio: 1/1)"', html)
        self.assertIn('media="(max-aspect-ratio: 2/1)"', html)
        self.assertIn('sizes="100vw"', html)
        self.assertIn("viewport-fit=cover", html)
        self.assertIn("interactive-widget=resizes-content", html)
        self.assertIn("env(safe-area-inset-bottom", html)
        self.assertIn('enterkeyhint="go"', html)
        self.assertNotIn("<script", html)
        self.assertNotIn("maximum-scale", html)
        self.assertNotIn("user-scalable", html)

    def test_login_form_preserves_and_escapes_an_internal_next_page(self):
        html = login_page.render(next_path="/api/profiles?tab=1")
        self.assertIn('name="next" value="/api/profiles?tab=1"', html)
        escaped = login_page.render(next_path='"><script>bad</script>')
        self.assertNotIn("<script>bad</script>", escaped)
        self.assertIn("&quot;&gt;&lt;script&gt;", escaped)

    def test_login_errors_and_csrf_are_escaped(self):
        html = login_page.render(error="<script>bad</script>", csrf='"><bad>')
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", html)
        self.assertIn('value="&quot;&gt;&lt;bad&gt;"', html)
        self.assertIn('aria-describedby="error"', html)
        self.assertIn('role="alert"', html)

    def test_login_initial_state_has_no_error(self):
        html = login_page.render()
        self.assertIn('<html lang="en">', html)
        self.assertIn('<main aria-label="Styx login">', html)
        self.assertIn('<button type="submit" aria-label="Sign in">', html)
        self.assertIn('placeholder="Password"', html)
        self.assertIn('aria-label="Password"', html)
        self.assertNotIn('role="alert"', html)
        self.assertNotIn('aria-invalid="true"', html)

    def test_session_roundtrip(self):
        with tempfile.TemporaryDirectory() as raw:
            key = sessions.load_or_create_key(Path(raw) / "session.key")
            token = sessions.issue(key, ttl=60)
            self.assertTrue(sessions.valid(key, token))
            self.assertFalse(sessions.valid(key, token + "x"))
            self.assertFalse(sessions.valid(b"0" * 32, token))

    def test_malformed_unicode_and_expired_sessions_are_rejected(self):
        for token in [None, "", "1.é.sig", "1.n.é", "x" * 4096, "1.n.sig"]:
            self.assertFalse(sessions.valid(b"x" * 32, token))
        with patch.object(sessions.time, "time", return_value=100):
            token = sessions.issue(b"x" * 32, ttl=1)
        with patch.object(sessions.time, "time", return_value=102):
            self.assertFalse(sessions.valid(b"x" * 32, token))

    def test_password_hash_change_changes_session_key(self):
        key = sessions.password_key(b"x" * 32, "old-hash")
        token = sessions.issue(key)
        self.assertTrue(sessions.valid(key, token))
        self.assertFalse(sessions.valid(sessions.password_key(b"x" * 32, "new-hash"), token))


if __name__ == "__main__":
    unittest.main()
