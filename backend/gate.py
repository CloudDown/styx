"""Cerberus gate: password page, then reverse-proxy to loopback Hermes.

Bind 127.0.0.1 only. Tor's hidden service is the only remote path in.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hmac
import logging
import re
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from http.cookiejar import CookieJar, DefaultCookiePolicy
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import headers as hdrs
from . import login_page
from . import passwords
from . import paths
from . import sessions
from .asset_transfer import accepts_gzip, compressible_asset, gzip_headers, gzip_stream
from .network import require_loopback
from .webapp_handoff import ENTRY_QUERY, HandoffError, WebappHandoff, strip_entry_query

log = logging.getLogger("styx.gate")

_FAIL_WINDOW = 15 * 60
_FAIL_MAX = 8
_LOGIN_MAX_BYTES = 16 * 1024
_LOGIN_TIMEOUT = 10.0
_LOGIN_DELAY = 0.4
_SESSION_CHECK_INTERVAL = 1.0


class _LoginLimiter:
    """One global budget per gate, including attempts currently in flight."""

    def __init__(self):
        self.fails: deque[float] = deque()
        self.pending = 0

    def reserve(self) -> float | None:
        # These synchronous operations cannot interleave on the ASGI event loop.
        now = time.monotonic()
        while self.fails and now - self.fails[0] > _FAIL_WINDOW:
            self.fails.popleft()
        if len(self.fails) + self.pending >= _FAIL_MAX:
            return None
        self.pending += 1
        return min(_LOGIN_DELAY * (len(self.fails) + 1), 3.0)

    def finish(self, success: bool) -> None:
        self.pending -= 1
        if not success:
            self.fails.append(time.monotonic())


class _ProxyResponse(StreamingResponse):
    """Close the upstream even if sending headers fails before iteration starts."""

    def __init__(self, upstream: httpx.Response, *, compress: bool = False):
        self.upstream = upstream
        super().__init__(gzip_stream(upstream) if compress else upstream.aiter_raw(),
                         status_code=upstream.status_code)
        headers = httpx.Headers(upstream.headers.raw, encoding="latin-1")
        self.raw_headers = [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in hdrs.inbound_response_headers(headers)
        ]
        if compress:
            self.raw_headers = gzip_headers(self.raw_headers)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.upstream.aclose()


def build_app(*, data_dir, upstream_host: str, upstream_port: int, secret: bytes,
              webapp_handoff: bool = False) -> Starlette:
    require_loopback(upstream_host)
    passwd_file = paths.passwd_path(data_dir)
    if not passwords.read_hash(passwd_file):
        raise SystemExit("no passphrase set — run: hermes styx passwd")

    client = httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=5.0),
        follow_redirects=False,
        limits=httpx.Limits(max_connections=64, max_keepalive_connections=16),
        trust_env=False,
        # A proxy must not carry upstream cookies between browser sessions.
        cookies=CookieJar(policy=DefaultCookiePolicy(allowed_domains=[])),
    )
    upstream_base = str(httpx.URL(scheme="http", host=upstream_host, port=upstream_port)).rstrip("/")
    limiter = _LoginLimiter()
    hash_slots = asyncio.Semaphore(2)
    render_slots = asyncio.Semaphore(2)
    handoff = WebappHandoff(upstream_host, upstream_port) if webapp_handoff else None

    def auth_key() -> bytes | None:
        stored = passwords.read_hash(passwd_file)
        return sessions.password_key(secret, stored) if stored else None

    def authed(connection) -> bool:
        key = auth_key()
        return key is not None and sessions.valid(key, connection.cookies.get(sessions.COOKIE))

    async def login_response(request: Request, error: str = "", status_code: int = 200, *,
                             csrf: str | None = None) -> Response:
        csrf = csrf or sessions.new_csrf()
        compressed = accepts_gzip(request.headers.get("accept-encoding", ""))
        def render():
            body = login_page.render(error=error, csrf=csrf).encode("utf-8")
            # Level 1 can barely compress the inline JPEG on some zlib builds.
            return gzip.compress(body, compresslevel=6, mtime=0) if compressed else body
        async with render_slots:
            work = asyncio.create_task(asyncio.to_thread(render))
            cancelled = False
            while True:
                try:
                    body = await asyncio.shield(work)
                    break
                except asyncio.CancelledError:
                    if work.cancelled():
                        raise
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
        resp = HTMLResponse(body, status_code=status_code)
        resp.headers["Vary"] = "Accept-Encoding"
        if compressed:
            resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.set_cookie(
            sessions.CSRF_COOKIE, csrf, httponly=True, samesite="lax",
            max_age=600, path="/login",
        )
        return resp

    async def verify(password: str, stored: str) -> bool:
        async with hash_slots:
            work = asyncio.create_task(asyncio.to_thread(passwords.verify_password, password, stored))
            cancelled = False
            while True:
                try:
                    result = await asyncio.shield(work)
                    break
                except asyncio.CancelledError:
                    if work.cancelled():
                        raise
                    # Even repeated cancellation must not release capacity
                    # while the non-cancellable scrypt thread is still running.
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
            return result

    async def login_get(request: Request) -> Response:
        if authed(request):
            return RedirectResponse("/", status_code=303)
        csrf = request.cookies.get(sessions.CSRF_COOKIE) or ""
        # Repeated GETs / another login tab must not invalidate an open form.
        if not re.fullmatch(r"[A-Za-z0-9_-]{32}", csrf):
            csrf = None
        return await login_response(request, csrf=csrf)

    async def login_post(request: Request) -> Response:
        delay = limiter.reserve()
        if delay is None:
            resp = await login_response(request, "Too many attempts. Try again later.", 429)
            resp.headers["Retry-After"] = str(_FAIL_WINDOW)
            return resp
        success = False
        try:
            body = bytearray()
            try:
                async with asyncio.timeout(_LOGIN_TIMEOUT):
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > _LOGIN_MAX_BYTES:
                            return await login_response(request, "Form submission is too large.", 413)
                        body.extend(chunk)
                form = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True, max_num_fields=8)
            except TimeoutError:
                return await login_response(request, "Form submission timed out.", 408)
            except ValueError:
                return await login_response(request, "Invalid form submission.", 400)
            csrf_form = form.get("csrf", [""])[0]
            csrf_cookie = request.cookies.get(sessions.CSRF_COOKIE) or ""
            password = form.get("password", [""])[0]
            await asyncio.sleep(delay)
            ok_csrf = bool(csrf_form) and hmac.compare_digest(
                csrf_form.encode("utf-8"), csrf_cookie.encode("utf-8"),
            )
            stored = passwords.read_hash(passwd_file)
            if not ok_csrf or not stored or not await verify(password, stored):
                return await login_response(request, "Incorrect password.", 401)
            # Reject a login whose password was replaced during verification.
            if passwords.read_hash(passwd_file) != stored:
                return await login_response(request, "Please try again.", 401)
            token = sessions.issue(sessions.password_key(secret, stored))
            success = True
        finally:
            limiter.finish(success)
        nxt = request.query_params.get("next") or "/"
        if not nxt.startswith("/") or nxt.startswith(("//", "/\\")):
            nxt = "/"
        launch_started = time.monotonic()
        if handoff and urlsplit(nxt).path == "/":
            try:
                # The password is already verified. Skip the otherwise redundant
                # round trip through GET /, without pre-issuing/caching a ticket.
                target = await handoff.launch(token, urlsplit(nxt).query)
                resp = RedirectResponse(target or nxt, status_code=303)
            except HandoffError as exc:
                resp = HTMLResponse(str(exc), status_code=503)
            if passwords.read_hash(passwd_file) != stored:
                return await login_response(request, "Please try again.", 401)
            resp.headers["Server-Timing"] = f"styx-launch;dur={(time.monotonic() - launch_started) * 1000:.1f}"
        else:
            resp = RedirectResponse(nxt, status_code=303)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.set_cookie(
            sessions.COOKIE, token, httponly=True, samesite="lax",
            max_age=sessions.TTL_SECONDS, path="/",
        )
        resp.delete_cookie(sessions.CSRF_COOKIE, path="/login")
        return resp

    async def logout(request: Request) -> Response:
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(sessions.COOKIE, path="/")
        return resp

    async def proxy_http(request: Request) -> Response:
        if not authed(request):
            if request.url.path == "/favicon.ico":
                # Browsers ask for this automatically; do not redirect a
                # background image request into the login/CSRF flow.
                return Response(status_code=204)
            dest = request.url.path
            if request.url.query:
                dest += "?" + request.url.query
            return RedirectResponse("/login?" + urlencode({"next": dest}), status_code=303)
        query = request.url.query
        if handoff and request.method == "GET" and request.url.path == "/":
            session = request.cookies.get(sessions.COOKIE) or ""
            if not handoff.consume(request.query_params.get(ENTRY_QUERY), session):
                launch_started = time.monotonic()
                try:
                    target = await handoff.launch(session, query)
                except HandoffError as exc:
                    return HTMLResponse(str(exc), status_code=503, headers={
                        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                    })
                # The password may have changed while the host CLI ran.
                if not authed(request):
                    return RedirectResponse("/login", status_code=303)
                if target:
                    return RedirectResponse(target, status_code=303, headers={
                        "Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                        "Server-Timing": f"styx-launch;dur={(time.monotonic() - launch_started) * 1000:.1f}",
                    })
            query = strip_entry_query(query)
        url = upstream_base + request.url.path
        if query:
            url += "?" + query
        req_headers = hdrs.outbound_headers(
            request.headers, upstream_host=upstream_host, upstream_port=upstream_port,
        )
        try:
            upstream = await client.send(
                httpx.Request(
                    request.method, url, headers=req_headers, content=request.stream(),
                ),
                stream=True,
            )
        except httpx.RequestError as exc:
            log.warning("upstream error: %s", exc)
            return HTMLResponse("Hermes is not reachable on loopback.", status_code=502)

        return _ProxyResponse(upstream, compress=compressible_asset(request, upstream))

    async def proxy_ws(websocket: WebSocket) -> None:
        if not authed(websocket):
            await websocket.close(code=4401)
            return
        path = websocket.url.path
        query = websocket.url.query
        ws_url = upstream_base.replace("http:", "ws:", 1) + path
        if query:
            ws_url += "?" + query
        extra = hdrs.outbound_headers(
            websocket.headers, upstream_host=upstream_host, upstream_port=upstream_port,
            websocket=True,
        )
        subprotocols = []
        raw_proto = websocket.headers.get("sec-websocket-protocol")
        if raw_proto:
            subprotocols = [p.strip() for p in raw_proto.split(",") if p.strip()]
        try:
            import websockets
        except ImportError:
            await websocket.close(code=1011)
            return
        connect_kw: dict = {
            "additional_headers": extra, "max_size": None, "ping_interval": 20,
            "proxy": None,
        }
        if subprotocols:
            connect_kw["subprotocols"] = subprotocols
        try:
            upstream = await websockets.connect(ws_url, **connect_kw)
        except Exception:
            log.exception("ws upstream connect failed")
            await websocket.close(code=1011)
            return

        async def client_to_up() -> None:
            try:
                while True:
                    msg = await websocket.receive()
                    if msg["type"] == "websocket.disconnect":
                        break
                    if msg.get("text") is not None:
                        await upstream.send(msg["text"])
                    elif msg.get("bytes") is not None:
                        await upstream.send(msg["bytes"])
            except (WebSocketDisconnect, websockets.ConnectionClosed):
                pass

        async def up_to_client() -> None:
            try:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)
            except (WebSocketDisconnect, websockets.ConnectionClosed):
                pass

        async def watch_session() -> None:
            while authed(websocket):
                await asyncio.sleep(_SESSION_CHECK_INTERVAL)
            await websocket.close(code=4401)

        tasks = []
        try:
            await websocket.accept(subprotocol=upstream.subprotocol)
            tasks = [
                asyncio.create_task(client_to_up()),
                asyncio.create_task(up_to_client()),
                asyncio.create_task(watch_session()),
            ]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await upstream.close()
            try:
                await websocket.close()
            except Exception:
                pass

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            await client.aclose()

    return Starlette(
        routes=[
            Route("/login", login_get, methods=["GET"]),
            Route("/login", login_post, methods=["POST"]),
            Route("/logout", logout, methods=["GET", "POST"]),
            WebSocketRoute("/{path:path}", proxy_ws),
            Route("/{path:path}", proxy_http, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]),
        ],
        lifespan=lifespan,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="styx.gate")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--webapp-handoff", action="store_true")
    args = parser.parse_args(argv)
    from pathlib import Path

    data_dir = Path(args.data_dir)
    if args.bind not in {"127.0.0.1", "::1", "localhost"}:
        print("refusing non-loopback bind", file=sys.stderr)
        return 2
    secret = sessions.load_or_create_key(paths.session_key_path(data_dir))
    app = build_app(
        data_dir=data_dir,
        upstream_host=args.upstream_host,
        upstream_port=args.upstream_port,
        secret=secret,
        webapp_handoff=args.webapp_handoff,
    )
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    uvicorn.run(app, host=args.bind, port=args.port, log_level="warning", access_log=False, workers=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
