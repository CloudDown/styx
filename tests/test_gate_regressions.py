from __future__ import annotations

import asyncio
import gzip
import inspect
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from starlette.requests import ClientDisconnect

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import gate, passwords, sessions  # noqa: E402


class Chunks(httpx.AsyncByteStream):
    def __init__(self, *chunks):
        self.chunks = chunks
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closed = True


class Transport(httpx.AsyncBaseTransport):
    """Unlike MockTransport, don't pre-buffer the request stream."""

    def __init__(self, handler):
        self.handler = handler

    async def handle_async_request(self, request):
        result = self.handler(request)
        return await result if inspect.isawaitable(result) else result


class GateRegressions(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.object(gate, "_LOGIN_DELAY", 0))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.secret = b"x" * 32
        passwords.write_hash(self.root / "passwd", "old-password")
        self.handler = lambda request: httpx.Response(200, stream=Chunks(b"ok"))
        client_type = httpx.AsyncClient
        def make_client(**kwargs):
            self.upstream = client_type(transport=Transport(lambda req: self.handler(req)), **kwargs)
            return self.upstream
        with patch.object(gate.httpx, "AsyncClient", side_effect=make_client):
            self.app = gate.build_app(
                data_dir=self.root, upstream_host="127.0.0.1",
                upstream_port=9120, secret=self.secret,
            )
        await self.enterAsyncContext(self.app.router.lifespan_context(self.app))
        self.browser = client_type(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test.local",
        )
        self.addAsyncCleanup(self.browser.aclose)

    async def login(self, password="old-password"):
        await self.browser.get("/login")
        csrf = self.browser.cookies[sessions.CSRF_COOKIE]
        return await self.browser.post("/login", data={"csrf": csrf, "password": password})

    async def test_repeated_login_gets_do_not_invalidate_an_open_form(self):
        await self.browser.get("/login")
        csrf = self.browser.cookies[sessions.CSRF_COOKIE]
        await self.browser.get("/login?next=/favicon.ico")
        self.assertEqual(self.browser.cookies[sessions.CSRF_COOKIE], csrf)
        response = await self.browser.post("/login", data={"csrf": csrf, "password": "old-password"})
        self.assertEqual(response.status_code, 303)

    async def test_unauthenticated_favicon_does_not_touch_login_cookies(self):
        await self.browser.get("/login")
        csrf = self.browser.cookies[sessions.CSRF_COOKIE]
        response = await self.browser.get("/favicon.ico")
        self.assertEqual(response.status_code, 204)
        self.assertNotIn("set-cookie", response.headers)
        self.assertEqual(self.browser.cookies[sessions.CSRF_COOKIE], csrf)

    async def test_preserves_gzip_and_separate_cookies(self):
        self.assertEqual((await self.login()).status_code, 303)
        content = gzip.compress(b"uncompressed")
        body = Chunks(content)
        self.handler = lambda req: httpx.Response(
            200, headers=[
                ("content-encoding", "gzip"), ("content-length", str(len(content))),
                ("set-cookie", "one=1; Path=/"), ("set-cookie", "two=2; Path=/"),
            ], stream=body,
        )
        response = await self.browser.get("/")
        self.assertEqual(response.headers.get("content-encoding"), "gzip")
        self.assertEqual(response.content, b"uncompressed")
        self.assertEqual(response.headers.get_list("set-cookie"), ["one=1; Path=/", "two=2; Path=/"])
        self.assertTrue(body.closed)

    async def test_login_compression_preserves_the_exact_page_and_csrf(self):
        identity = await self.browser.get("/login", headers={"accept-encoding": "identity"})
        encoded = await self.browser.get("/login", headers={"accept-encoding": "gzip"})
        self.assertEqual(identity.content, encoded.content)
        self.assertNotIn("content-encoding", identity.headers)
        self.assertEqual(encoded.headers["content-encoding"], "gzip")
        self.assertEqual(encoded.headers["cache-control"], "no-store")
        self.assertLess(int(encoded.headers["content-length"]), len(identity.content) * 0.85)
        # The complete usable form no longer transfers the painting on each GET.
        self.assertLess(encoded.text.index('name="password"'), 5000)
        self.assertNotIn("base64,", encoded.text)
        self.assertLess(len(identity.content), 6000)

    async def test_only_the_public_painting_is_immutable_and_requires_no_session(self):
        url = gate.login_page.background_url()
        response = await self.browser.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, gate.login_page.background_bytes())
        self.assertEqual(response.headers["content-type"], "image/jpeg")
        self.assertIn("immutable", response.headers["cache-control"])
        self.assertNotIn("set-cookie", response.headers)
        self.assertNotIn("content-encoding", response.headers)
        etag = response.headers["etag"]
        for tag in (etag, "W/" + etag, '"other", ' + etag, "*"):
            cached = await self.browser.get(url, headers={"if-none-match": tag})
            self.assertEqual(cached.status_code, 304)
            self.assertEqual(cached.content, b"")
            self.assertNotIn("set-cookie", cached.headers)
        head = await self.browser.head(url)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertEqual(int(head.headers["content-length"]), len(response.content))
        # No directory, arbitrary image or upstream asset becomes public.
        for path in ("/_styx/login-background-wrong.jpg", "/assets/login-background.jpg",
                     "/_styx/../passwd"):
            self.assertEqual((await self.browser.get(path)).status_code, 303)
        login = await self.browser.get("/login")
        self.assertEqual(login.headers["cache-control"], "no-store")

    async def test_valid_login_does_not_wait_for_the_failure_backoff(self):
        with patch.object(gate, "_LOGIN_DELAY", 0.4), \
                patch.object(gate.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            response = await self.login()
        self.assertEqual(response.status_code, 303)
        sleep.assert_not_awaited()

    async def test_invalid_logins_keep_the_full_progressive_backoff(self):
        with patch.object(gate, "_LOGIN_DELAY", 0.4), \
                patch.object(gate.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            self.assertEqual((await self.login("wrong")).status_code, 401)
            self.assertEqual((await self.login("wrong")).status_code, 401)
            # A legitimate login after failures still has no artificial wait.
            self.assertEqual((await self.login()).status_code, 303)
        self.assertEqual([call.args[0] for call in sleep.await_args_list], [0.4, 0.8])

    async def test_failed_attempts_stay_pending_during_backoff(self):
        await self.browser.get("/login")
        csrf = self.browser.cookies[sessions.CSRF_COOKIE]
        all_waiting, release = asyncio.Event(), asyncio.Event()
        waiting = 0

        async def backoff(delay):
            nonlocal waiting
            waiting += 1
            if waiting == gate._FAIL_MAX:
                all_waiting.set()
            await release.wait()

        with patch.object(passwords, "verify_password", return_value=False), \
                patch.object(gate.asyncio, "sleep", side_effect=backoff):
            requests = [
                asyncio.create_task(self.browser.post(
                    "/login", data={"csrf": csrf, "password": "wrong"},
                )) for _ in range(gate._FAIL_MAX)
            ]
            try:
                await asyncio.wait_for(all_waiting.wait(), timeout=3)
                blocked = await self.browser.post(
                    "/login", data={"csrf": csrf, "password": "old-password"},
                )
                self.assertEqual(blocked.status_code, 429)
            finally:
                release.set()
                responses = await asyncio.gather(*requests)
            self.assertTrue(all(response.status_code == 401 for response in responses))

    async def test_public_scripts_are_streamed_compressed_without_changing_cache_policy(self):
        await self.login()
        content = b"const hello = 'unchanged';\n" * 1000
        body = Chunks(content[:5000], content[5000:])
        self.handler = lambda req: httpx.Response(200, headers={
            "content-type": "text/javascript", "content-length": str(len(content)),
            "cache-control": "public, max-age=31536000, immutable", "etag": '"v1"',
        }, stream=body)
        async with self.browser.stream("GET", "/assets/main-123abcXY.js",
                                       headers={"accept-encoding": "gzip"}) as response:
            encoded = b"".join([chunk async for chunk in response.aiter_raw()])
        self.assertEqual(gzip.decompress(encoded), content)
        self.assertLess(len(encoded), len(content) // 10)
        self.assertNotIn("content-length", response.headers)
        self.assertEqual(response.headers["etag"], 'W/"v1"')
        self.assertIn("Accept-Encoding", response.headers["vary"])
        self.assertEqual(response.headers["cache-control"], "public, max-age=31536000, immutable")
        self.assertTrue(body.closed)

    async def test_assets_still_require_cerberus_and_no_api_compression_is_added(self):
        response = await self.browser.get("/assets/main-123abcXY.js")
        self.assertEqual(response.status_code, 303)
        await self.login()
        content = b"private" * 1000
        self.handler = lambda req: httpx.Response(200, headers={
            "content-type": "application/json", "content-length": str(len(content)),
            "cache-control": "no-store",
        }, stream=Chunks(content))
        response = await self.browser.get("/api/profiles")
        self.assertNotIn("content-encoding", response.headers)
        self.assertEqual(response.content, content)
        self.assertEqual(response.headers["content-length"], str(len(content)))

    async def test_preencoded_static_bytes_lengths_and_duplicate_cookies_stay_raw(self):
        await self.login()
        content = gzip.compress(b"static body" * 1000)
        body = Chunks(content)
        self.handler = lambda req: httpx.Response(200, headers=[
            ("content-type", "text/javascript"), ("content-encoding", "gzip"),
            ("content-length", str(len(content))),
            ("cache-control", "public, max-age=31536000, immutable"),
            ("set-cookie", "one=1; Path=/"), ("set-cookie", "two=2; Path=/"),
        ], stream=body)
        async with self.browser.stream("GET", "/assets/main-123abcXY.js") as response:
            encoded = b"".join([chunk async for chunk in response.aiter_raw()])
        self.assertEqual(encoded, content)
        self.assertEqual(response.headers["content-length"], str(len(content)))
        self.assertEqual(response.headers.get_list("set-cookie"), ["one=1; Path=/", "two=2; Path=/"])
        self.assertTrue(body.closed)

    async def test_concurrent_attempts_cannot_bypass_global_limit(self):
        await self.browser.get("/login")
        csrf = self.browser.cookies[sessions.CSRF_COOKIE]
        with patch.object(passwords, "verify_password", return_value=False) as verify:
            responses = await asyncio.gather(*(
                self.browser.post("/login", data={"csrf": csrf, "password": "wrong"})
                for _ in range(12)
            ))
        self.assertEqual(verify.call_count, 8)
        self.assertEqual(sum(r.status_code == 429 for r in responses), 4)

    async def test_password_change_revokes_sessions_and_reloads_hash(self):
        self.assertEqual((await self.login()).status_code, 303)
        self.assertEqual((await self.browser.get("/")).status_code, 200)
        passwords.write_hash(self.root / "passwd", "new-password")
        self.assertEqual((await self.browser.get("/")).status_code, 303)
        self.assertEqual((await self.login()).status_code, 401)
        self.assertEqual((await self.login("new-password")).status_code, 303)
        self.assertEqual((await self.browser.get("/")).status_code, 200)

    async def test_limits_login_body_even_without_content_length(self):
        async def chunks():
            for _ in range(32):
                yield b"x" * 1024
        with patch.object(passwords, "verify_password") as verify:
            response = await self.browser.post("/login", content=chunks())
        self.assertEqual(response.status_code, 413)
        verify.assert_not_called()

    async def test_upload_reaches_upstream_before_source_is_exhausted(self):
        self.assertEqual((await self.login()).status_code, 303)
        consumed = 0

        async def chunks():
            nonlocal consumed
            for _ in range(4):
                consumed += 1
                yield b"x" * 1024

        async def handler(request):
            self.assertEqual(consumed, 0)
            received = 0
            async for chunk in request.stream:
                received += len(chunk)
            self.assertEqual(received, 4096)
            return httpx.Response(200, stream=Chunks(b"uploaded"))

        self.handler = handler
        response = await self.browser.post("/upload", content=chunks())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(consumed, 4)

    async def test_scrypt_does_not_block_event_loop(self):
        await self.browser.get("/login")
        csrf = self.browser.cookies[sessions.CSRF_COOKIE]
        loop_thread = threading.get_ident()
        def verify(password, stored):
            self.assertNotEqual(threading.get_ident(), loop_thread)
            return False
        with patch.object(passwords, "verify_password", side_effect=verify):
            response = await self.browser.post("/login", data={"csrf": csrf, "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertIn('<p id="error" role="alert">Incorrect password.</p>', response.text)

    async def test_slow_login_has_a_deadline(self):
        async def chunks():
            await asyncio.sleep(0.1)
            yield b"password=x"
        with patch.object(gate, "_LOGIN_TIMEOUT", 0.01):
            response = await self.browser.post("/login", content=chunks())
        self.assertEqual(response.status_code, 408)

    async def test_password_change_during_verification_does_not_issue_token(self):
        await self.browser.get("/login")
        csrf = self.browser.cookies[sessions.CSRF_COOKIE]
        def replace_password(password, stored):
            passwords.write_hash(self.root / "passwd", "changed-during-login")
            return True
        with patch.object(passwords, "verify_password", side_effect=replace_password):
            response = await self.browser.post("/login", data={"csrf": csrf, "password": "old-password"})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(sessions.COOKIE, self.browser.cookies)

    async def test_proxy_does_not_share_upstream_cookies_between_browsers(self):
        self.assertEqual((await self.login()).status_code, 303)
        received = []
        def handler(request):
            received.append(request.headers.get("cookie", ""))
            return httpx.Response(
                200, headers={"set-cookie": "private=browser-one; Path=/"}, stream=Chunks(b"ok"),
            )
        self.handler = handler
        await self.browser.get("/")
        self.assertEqual(self.browser.cookies["private"], "browser-one")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test.local",
            cookies={sessions.COOKIE: self.browser.cookies[sessions.COOKIE]},
        ) as other:
            await other.get("/")
        self.assertEqual(received, ["", ""])
        self.assertEqual(len(self.upstream.cookies), 0)

    async def test_repeated_cancellation_does_not_abandon_scrypt(self):
        await self.browser.get("/login")
        csrf = self.browser.cookies[sessions.CSRF_COOKIE]
        entered, release = threading.Event(), threading.Event()
        def verify(password, stored):
            entered.set()
            release.wait(timeout=3)
            return False
        with patch.object(passwords, "verify_password", side_effect=verify):
            request = asyncio.create_task(self.browser.post(
                "/login", data={"csrf": csrf, "password": "wrong"},
            ))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                request.cancel()
                await asyncio.sleep(0)
                request.cancel()
                await asyncio.sleep(0)
                self.assertFalse(request.done())
            finally:
                release.set()
                await asyncio.gather(request, return_exceptions=True)
        self.assertTrue(request.cancelled())

    async def test_scrypt_concurrency_stays_bounded(self):
        await self.browser.get("/login")
        csrf = self.browser.cookies[sessions.CSRF_COOKIE]
        lock = threading.Lock()
        two_running, release = threading.Event(), threading.Event()
        active = peak = 0

        def verify(password, stored):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    two_running.set()
            try:
                release.wait(timeout=3)
                return False
            finally:
                with lock:
                    active -= 1

        with patch.object(passwords, "verify_password", side_effect=verify):
            requests = [
                asyncio.create_task(self.browser.post("/login", data={"csrf": csrf, "password": "wrong"}))
                for _ in range(8)
            ]
            try:
                self.assertTrue(await asyncio.to_thread(two_running.wait, 1))
                self.assertEqual((await self.browser.get("/login")).status_code, 200)
            finally:
                release.set()
                results = await asyncio.gather(*requests)
        self.assertEqual(peak, 2)
        self.assertTrue(all(r.status_code == 401 for r in results))

    async def test_upstream_closes_if_client_disconnects_before_response_body(self):
        self.assertEqual((await self.login()).status_code, 303)
        body = Chunks(b"unread")
        self.handler = lambda req: httpx.Response(200, stream=body)
        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": "/", "raw_path": b"/", "query_string": b"",
            "headers": [(b"host", b"test.local"), (b"cookie", f"styx_session={self.browser.cookies[sessions.COOKIE]}".encode())],
            "client": ("127.0.0.1", 12345), "server": ("test.local", 80),
        }
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        async def send(message):
            raise OSError("client gone")
        with self.assertRaises(ClientDisconnect):
            await self.app(scope, receive, send)
        self.assertTrue(body.closed)

    async def test_refuses_non_loopback_upstream(self):
        with self.assertRaisesRegex(RuntimeError, "non-loopback"):
            gate.build_app(data_dir=self.root, upstream_host="0.0.0.0", upstream_port=9120, secret=self.secret)


class LoginLimiter(unittest.TestCase):
    def test_window_and_pending_attempts(self):
        clock = unittest.mock.Mock()
        clock.monotonic.return_value = 100.0
        with patch.object(gate, "time", clock):
            limiter = gate._LoginLimiter()
            for _ in range(8):
                self.assertIsNotNone(limiter.reserve())
            self.assertIsNone(limiter.reserve())
            for _ in range(8):
                limiter.finish(False)
            self.assertIsNone(limiter.reserve())
            clock.monotonic.return_value += gate._FAIL_WINDOW + 1
            self.assertIsNotNone(limiter.reserve())
            limiter.finish(True)
            self.assertFalse(limiter.fails)
