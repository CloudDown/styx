"""Cerberus gate: password page, then reverse-proxy to loopback Hermes.

Bind 127.0.0.1 only. Tor's hidden service is the only remote path in.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hmac
import json
import logging
import os
import re
import sys
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from http.cookiejar import CookieJar, DefaultCookiePolicy
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect, Request
from starlette.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import headers as hdrs
from . import login_page, passwords, paths, sessions, terminal, tui_webapp, webapp_mode
from .asset_transfer import accepts_gzip, asset_encoding, compressed_stream, encoding_headers
from .network import require_loopback
from .offload import run_in_thread
from .webapp_handoff import ENTRY_QUERY, HandoffError, WebappHandoff, strip_entry_query
from .webapp_preload import WebappPreload

log = logging.getLogger("styx.gate")

_FAIL_WINDOW = 15 * 60
_FAIL_MAX = 8
_LOGIN_MAX_BYTES = 16 * 1024
_LOGIN_TIMEOUT = 10.0
_LOGIN_DELAY = 0.4
_SESSION_CHECK_INTERVAL = 1.0
_NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
_NEXT_MAX = 2048


def _safe_next(raw: str | None) -> str:
    """Only an internal path, no scheme-relative or backslash form, bounded."""
    value = raw or ""
    if len(value) > _NEXT_MAX or "\r" in value or "\n" in value:
        return "/"
    if not value.startswith("/") or value.startswith(("//", "/\\")):
        return "/"
    return value


def _authority(value: str) -> tuple[str, int] | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if not parsed.hostname:
        return None
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return parsed.hostname.casefold(), port


def _same_origin(connection: Request | WebSocket) -> bool:
    """Browsers send Origin on WebSockets and mutations; non-browser clients may not."""
    origin = connection.headers.get("origin")
    if not origin:
        return True
    host = connection.headers.get("host", "")
    return _authority(origin) is not None and _authority(origin) == _authority("http://" + host)


class _LoginLimiter:
    """One global budget per gate, including attempts currently in flight."""

    def __init__(self) -> None:
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

    def __init__(
        self,
        upstream: httpx.Response,
        *,
        encoding: str | None = None,
        gzip_level: int = 1,
        links: tuple[str, ...] = (),
    ) -> None:
        self.upstream = upstream
        super().__init__(
            compressed_stream(upstream, encoding, gzip_level=gzip_level)
            if encoding
            else upstream.aiter_raw(),
            status_code=upstream.status_code,
        )
        headers = httpx.Headers(upstream.headers.raw, encoding="latin-1")
        self.raw_headers = [
            (key.lower().encode("latin-1"), value.encode("latin-1"))
            for key, value in hdrs.inbound_response_headers(headers)
        ]
        if encoding:
            self.raw_headers = encoding_headers(self.raw_headers, encoding)
        self.raw_headers.extend((b"link", link.encode("ascii")) for link in links)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.upstream.aclose()


def build_app(
    *,
    data_dir: Path,
    upstream_host: str,
    upstream_port: int,
    secret: bytes,
    webapp_handoff: bool = False,
) -> Starlette:
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
    upstream_base = str(httpx.URL(scheme="http", host=upstream_host, port=upstream_port)).rstrip(
        "/"
    )
    limiter = _LoginLimiter()
    revoked = sessions.Revocations()
    hash_slots = asyncio.Semaphore(2)
    render_slots = asyncio.Semaphore(2)
    handoff = WebappHandoff(upstream_host, upstream_port) if webapp_handoff else None
    preload = WebappPreload(client, upstream_base) if handoff else None
    login_backgrounds = {
        login_page.background_url(variant, fmt): (variant, fmt)
        for fmt in login_page.BACKGROUND_FORMATS
        for variant in login_page.BACKGROUND_SIZES
    }

    def auth_key() -> bytes | None:
        stored = passwords.read_hash(passwd_file)
        return sessions.password_key(secret, stored) if stored else None

    def authed(connection: Request | WebSocket) -> bool:
        key = auth_key()
        token = connection.cookies.get(sessions.COOKIE)
        return key is not None and not revoked.contains(token) and sessions.valid(key, token)

    async def watch_session(connection: WebSocket) -> None:
        """Close a long-lived socket within one second of a password change."""
        while authed(connection):
            await asyncio.sleep(_SESSION_CHECK_INTERVAL)
        await connection.close(code=4401)

    async def cancel_tasks(tasks: list[asyncio.Task[None]]) -> None:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def login_response(
        request: Request,
        error: str = "",
        status_code: int = 200,
        *,
        csrf: str | None = None,
        next_path: str = "/",
    ) -> Response:
        csrf = csrf or sessions.new_csrf()
        compressed = accepts_gzip(request.headers.get("accept-encoding", ""))

        def render() -> bytes:
            body = login_page.render(error=error, csrf=csrf, next_path=next_path).encode("utf-8")
            # The form is tiny; the public painting has its own immutable URL.
            return gzip.compress(body, compresslevel=6, mtime=0) if compressed else body

        async with render_slots:
            body = await run_in_thread(render)
        resp = HTMLResponse(body, status_code=status_code)
        resp.headers["Vary"] = "Accept-Encoding"
        if compressed:
            resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        )
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.set_cookie(
            sessions.CSRF_COOKIE, csrf, httponly=True, samesite="lax", max_age=600, path="/login"
        )
        return resp

    async def login_background(request: Request) -> Response:
        variant, fmt = login_backgrounds[request.url.path]
        image = login_page.background_bytes(variant, fmt)
        etag = login_page.background_etag(variant, fmt)
        headers = {
            "Cache-Control": "public, max-age=31536000, immutable",
            "ETag": etag,
            "X-Content-Type-Options": "nosniff",
        }
        tags = request.headers.get("if-none-match", "").split(",")
        if any(tag.strip().removeprefix("W/") in (etag, "*") for tag in tags):
            return Response(status_code=304, headers=headers)
        return Response(image, media_type=login_page.BACKGROUND_FORMATS[fmt], headers=headers)

    async def verify(password: str, stored: str) -> bool:
        async with hash_slots:
            return await run_in_thread(passwords.verify_password, password, stored)

    async def login_get(request: Request) -> Response:
        if authed(request):
            return RedirectResponse("/", status_code=303)
        csrf = request.cookies.get(sessions.CSRF_COOKIE) or ""
        # Repeated GETs / another login tab must not invalidate an open form.
        if not re.fullmatch(r"[A-Za-z0-9_-]{32}", csrf):
            csrf = None
        return await login_response(
            request, csrf=csrf, next_path=_safe_next(request.query_params.get("next"))
        )

    async def login_post(request: Request) -> Response:
        next_path = _safe_next(request.query_params.get("next"))
        delay = limiter.reserve()
        if delay is None:
            resp = await login_response(
                request, "Too many attempts. Try again later.", 429, next_path=next_path
            )
            resp.headers["Retry-After"] = str(_FAIL_WINDOW)
            return resp
        success = False
        try:
            body = bytearray()
            try:
                async with asyncio.timeout(_LOGIN_TIMEOUT):
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > _LOGIN_MAX_BYTES:
                            return await login_response(
                                request, "Form submission is too large.", 413, next_path=next_path
                            )
                        body.extend(chunk)
                form = parse_qs(
                    body.decode("utf-8", errors="replace"), keep_blank_values=True, max_num_fields=8
                )
                # The hidden field is authoritative once the form parsed.
                next_path = _safe_next(form.get("next", [next_path])[0])
            except TimeoutError:
                return await login_response(
                    request, "Form submission timed out.", 408, next_path=next_path
                )
            except ValueError:
                return await login_response(
                    request, "Invalid form submission.", 400, next_path=next_path
                )
            csrf_form = form.get("csrf", [""])[0]
            csrf_cookie = request.cookies.get(sessions.CSRF_COOKIE) or ""
            password = form.get("password", [""])[0]
            ok_csrf = bool(csrf_form) and hmac.compare_digest(
                csrf_form.encode("utf-8"), csrf_cookie.encode("utf-8")
            )
            stored = passwords.read_hash(passwd_file)
            if not ok_csrf or not stored or not await verify(password, stored):
                # Keep the full backoff and pending reservation for failures,
                # without slowing down a successfully authenticated user.
                await asyncio.sleep(delay)
                return await login_response(
                    request, "Incorrect password.", 401, next_path=next_path
                )
            # Reject a login whose password was replaced during verification.
            if passwords.read_hash(passwd_file) != stored:
                await asyncio.sleep(delay)
                return await login_response(request, "Please try again.", 401, next_path=next_path)
            token = sessions.issue(sessions.password_key(secret, stored))
            success = True
        finally:
            limiter.finish(success)
        nxt = next_path
        launch_started = time.monotonic()
        destination = urlsplit(nxt)
        root_query = dict(parse_qsl(destination.query))
        mode = webapp_mode.read_mode(data_dir)
        view = root_query.get(webapp_mode.VIEW_QUERY)
        selected_view = view if view in webapp_mode.MODES else mode
        if destination.path == "/" and selected_view == "tui":
            resp = RedirectResponse(tui_webapp.TUI, status_code=303)
        elif handoff and destination.path == "/":
            try:
                # The password is already verified. Skip the otherwise redundant
                # round trip through GET /, without pre-issuing/caching a ticket.
                target = await handoff.launch(token, destination.query)
                resp = RedirectResponse(target or nxt, status_code=303)
            except HandoffError as exc:
                resp = HTMLResponse(str(exc), status_code=503)
            if passwords.read_hash(passwd_file) != stored:
                return await login_response(request, "Please try again.", 401, next_path=next_path)
            resp.headers["Server-Timing"] = (
                f"styx-launch;dur={(time.monotonic() - launch_started) * 1000:.1f}"
            )
        else:
            resp = RedirectResponse(nxt, status_code=303)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.set_cookie(
            sessions.COOKIE,
            token,
            httponly=True,
            samesite="lax",
            max_age=sessions.TTL_SECONDS,
            path="/",
        )
        resp.delete_cookie(sessions.CSRF_COOKIE, path="/login")
        return resp

    async def logout(request: Request) -> Response:
        revoked.revoke(request.cookies.get(sessions.COOKIE))
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(sessions.COOKIE, path="/")
        return resp

    async def tui_shell(request: Request) -> Response:
        if not authed(request):
            return RedirectResponse(
                "/login?" + urlencode({"next": tui_webapp.TUI}), status_code=303, headers=_NO_STORE
            )
        return tui_webapp.response(
            request.headers.get("accept-encoding", ""), request.headers.get("if-none-match", "")
        )

    async def tui_asset(request: Request) -> Response:
        if not authed(request):
            return RedirectResponse(
                "/login?" + urlencode({"next": tui_webapp.TUI}), status_code=303, headers=_NO_STORE
            )
        return tui_webapp.asset(
            request.path_params["asset"],
            request.headers.get("accept-encoding", ""),
            request.headers.get("if-none-match", ""),
        )

    async def tui_socket(websocket: WebSocket) -> None:
        """One fixed command in a real PTY. Nothing here is client-chosen."""
        if not _same_origin(websocket):
            await websocket.close(code=4403)
            return
        if not authed(websocket):
            await websocket.close(code=4401)
            return
        argv = terminal.command()
        await websocket.accept()
        if argv is None or os.name != "posix":
            reason = (
                "The hermes launcher is not on this host's PATH."
                if argv is None
                else "This host has no POSIX pseudo-terminal."
            )
            await websocket.send_text(f"\r\n\x1b[31m{reason}\x1b[0m\r\n")
            await websocket.close(code=1011)
            return
        env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
        try:
            session = terminal.Terminal(argv, cwd=os.path.expanduser("~"), env=env)
        except OSError as exc:
            log.warning("tui: could not start the terminal: %s", exc)
            await websocket.send_text("\r\n\x1b[31mCould not start the terminal.\x1b[0m\r\n")
            await websocket.close(code=1011)
            return

        async def pump_out() -> None:
            while True:
                chunk = await session.reader.get()
                if chunk is None:
                    return
                await websocket.send_bytes(chunk)

        async def pump_in() -> None:
            while True:
                message = await websocket.receive()
                if message["type"] == "websocket.disconnect":
                    return
                raw = message.get("bytes")
                if raw:
                    session.write(raw)
                    continue
                text = message.get("text") or ""
                if text.startswith("{"):
                    try:
                        command = json.loads(text)
                    except ValueError:
                        command = None
                    if isinstance(command, dict) and command.get("type") == "resize":
                        with suppress(TypeError, ValueError):
                            session.resize(
                                int(command.get("cols", 80)), int(command.get("rows", 24))
                            )
                        continue
                session.write(text.encode())

        tasks = [
            asyncio.create_task(pump_out()),
            asyncio.create_task(pump_in()),
            asyncio.create_task(watch_session(websocket)),
        ]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            await cancel_tasks(tasks)
            session.close()
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close()

    async def proxy_http(request: Request) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not _same_origin(request):
            return Response(status_code=403, headers=_NO_STORE)
        if not authed(request):
            if request.url.path == "/favicon.ico":
                # Browsers ask for this automatically; do not redirect a
                # background image request into the login/CSRF flow.
                return Response(status_code=204)
            dest = request.url.path
            if request.url.query:
                dest += "?" + request.url.query
            return RedirectResponse("/login?" + urlencode({"next": dest}), status_code=303)
        if preload and request.method == "GET" and request.url.path == "/webapp/launch":
            preload.warm()
        query = request.url.query
        if request.method == "GET" and request.url.path == "/":
            session = request.cookies.get(sessions.COOKIE) or ""
            view = request.query_params.get(webapp_mode.VIEW_QUERY)
            consumed = (
                handoff.consume(request.query_params.get(ENTRY_QUERY), session)
                if handoff
                else False
            )
            mode = webapp_mode.read_mode(data_dir)
            if view == "tui" or (not consumed and view != "hermes" and mode == "tui"):
                return RedirectResponse(tui_webapp.TUI, status_code=303, headers=_NO_STORE)
            if handoff and not consumed:
                launch_started = time.monotonic()
                try:
                    target = await handoff.launch(session, query)
                except HandoffError as exc:
                    return HTMLResponse(
                        str(exc),
                        status_code=503,
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
                    )
                # The password may have changed while the host CLI ran.
                if not authed(request):
                    return RedirectResponse("/login", status_code=303)
                if target:
                    return RedirectResponse(
                        target,
                        status_code=303,
                        headers={
                            "Cache-Control": "no-store",
                            "Referrer-Policy": "no-referrer",
                            "Server-Timing": f"styx-launch;dur={(time.monotonic() - launch_started) * 1000:.1f}",
                        },
                    )
            query = strip_entry_query(query)
            if view is not None:
                query = urlencode(
                    [
                        (k, v)
                        for k, v in parse_qsl(query, keep_blank_values=True)
                        if k != webapp_mode.VIEW_QUERY
                    ]
                )
        url = upstream_base + request.url.path
        if query:
            url += "?" + query
        req_headers = hdrs.outbound_headers(
            request.headers, upstream_host=upstream_host, upstream_port=upstream_port
        )
        # Normal reads have no request body. Avoid starting an empty chunked
        # upload to Hermes for every read (including aborted startup fetches).
        bodyless = (
            request.method in {"GET", "HEAD"}
            and request.headers.get("content-length", "0") == "0"
            and "transfer-encoding" not in request.headers
        )
        try:
            upstream = await client.send(
                httpx.Request(
                    request.method,
                    url,
                    headers=req_headers,
                    content=None if bodyless else request.stream(),
                ),
                stream=True,
            )
        except ClientDisconnect:
            return Response(status_code=499)
        except httpx.RequestError as exc:
            log.warning("upstream error: %s", exc)
            return HTMLResponse("Hermes is not reachable on loopback.", status_code=502)

        links = ()
        if (
            preload
            and request.method == "GET"
            and request.url.path == "/"
            and upstream.status_code == 200
            and upstream.headers.get("content-type", "").startswith("text/html")
        ):
            links = preload.current()
        # The official renderer sends several MB at cold boot. Negotiate a
        # smaller wire representation without caching or buffering a bundle.
        encoding = asset_encoding(request, upstream, prefer_zstd=handoff is not None)
        return _ProxyResponse(
            upstream, encoding=encoding, gzip_level=5 if handoff else 1, links=links
        )

    async def proxy_ws(websocket: WebSocket) -> None:
        if not _same_origin(websocket):
            await websocket.close(code=4403)
            return
        if not authed(websocket):
            await websocket.close(code=4401)
            return
        path = websocket.url.path
        query = websocket.url.query
        ws_url = upstream_base.replace("http:", "ws:", 1) + path
        if query:
            ws_url += "?" + query
        extra = hdrs.outbound_headers(
            websocket.headers,
            upstream_host=upstream_host,
            upstream_port=upstream_port,
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
            "additional_headers": extra,
            "max_size": None,
            "ping_interval": 20,
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

        tasks: list[asyncio.Task[None]] = []
        try:
            await websocket.accept(subprotocol=upstream.subprotocol)
            tasks = [
                asyncio.create_task(client_to_up()),
                asyncio.create_task(up_to_client()),
                asyncio.create_task(watch_session(websocket)),
            ]
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            await cancel_tasks(tasks)
            await upstream.close()
            with suppress(Exception):
                await websocket.close()

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if preload:
                await preload.close()
            await client.aclose()

    return Starlette(
        routes=[
            # Fixed, content-addressed public artwork only: no asset directory.
            *(Route(url, login_background, methods=["GET"]) for url in login_backgrounds),
            Route("/login", login_get, methods=["GET"]),
            Route("/login", login_post, methods=["POST"]),
            Route("/logout", logout, methods=["GET", "POST"]),
            # The terminal needs no upstream: it runs where the gate runs.
            Route(tui_webapp.TUI, tui_shell, methods=["GET"]),
            Route(tui_webapp.TUI + "/{asset}", tui_asset, methods=["GET"]),
            WebSocketRoute(tui_webapp.SOCKET, tui_socket),
            WebSocketRoute("/{path:path}", proxy_ws),
            Route(
                "/{path:path}",
                proxy_http,
                methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
            ),
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
    uvicorn.run(
        app, host=args.bind, port=args.port, log_level="warning", access_log=False, workers=1
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
