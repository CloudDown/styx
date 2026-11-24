"""The terminal interface: Hermes' own TUI, painted by xterm.js in the browser.

Only the shell and three immutable vendor files are served here. The terminal
stream comes from the PTY in :mod:`backend.terminal`; nothing is proxied.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
from functools import lru_cache
from starlette.responses import HTMLResponse, Response

from .asset_transfer import accepts_gzip
from .paths import PLUGIN_ROOT

TUI = "/_styx/tui"
SOCKET = TUI + "/ws"
_FILES = PLUGIN_ROOT / "assets" / "tui"
_VENDOR = {
    "xterm.js": "text/javascript; charset=utf-8",
    "addon-fit.js": "text/javascript; charset=utf-8",
    "xterm.css": "text/css; charset=utf-8",
}


def _digest(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


@lru_cache(maxsize=1)
def _vendor() -> dict[str, tuple[bytes, bytes, str]]:
    return {name: (raw := (_FILES / "vendor" / name).read_bytes(),
                   gzip.compress(raw, mtime=0), _digest(raw))
            for name in _VENDOR}


def asset(name: str, accept_encoding: str, if_none_match: str = "") -> Response:
    """One immutable vendor file, cached hard (the shell stamps a content version)."""
    entry = _vendor().get(name)
    if entry is None:
        return Response(status_code=404)
    raw, compressed, digest = entry
    etag = f'"{digest[:22]}"'
    headers = {"Cache-Control": "private, max-age=31536000, immutable", "ETag": etag,
               "X-Content-Type-Options": "nosniff", "Vary": "Accept-Encoding"}
    if if_none_match and etag in [tag.strip() for tag in if_none_match.split(",")]:
        return Response(status_code=304, headers=headers)
    if accepts_gzip(accept_encoding):
        raw = compressed
        headers["Content-Encoding"] = "gzip"
    return Response(raw, media_type=_VENDOR[name], headers=headers)


@lru_cache(maxsize=1)
def _shell() -> tuple[bytes, bytes, str, str]:
    html = (_FILES / "index.html").read_text(encoding="utf-8")
    css = (_FILES / "tui.css").read_text(encoding="utf-8")
    js = (_FILES / "tui.js").read_text(encoding="utf-8")
    vendor = _vendor()
    version = {name: vendor[name][2][:12] for name in vendor}
    body = html.replace("<!-- STYX_STYLE -->", f"<style>{css}</style>", 1)
    body = (body.replace("<!-- STYX_SCRIPT -->", f"<script>{js}</script>", 1)
            .replace("__XTERM_CSS__", f"{TUI}/xterm.css?v={version['xterm.css']}")
            .replace("__XTERM__", f"{TUI}/xterm.js?v={version['xterm.js']}")
            .replace("__FIT__", f"{TUI}/addon-fit.js?v={version['addon-fit.js']}"))
    body = body.encode()
    # `'self'` covers the three vendor files. xterm writes its own <style>
    # elements (dynamic, so no hash is possible); scripts stay hash-locked.
    csp = (f"default-src 'none'; script-src 'self' 'sha256-{_digest(js.encode())}'; "
           "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'none'; "
           "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
    return body, gzip.compress(body, mtime=0), csp, 'W/"' + _digest(body)[:22] + '"'


def response(accept_encoding: str, if_none_match: str = "") -> Response:
    body, compressed, csp, etag = _shell()
    headers = {"Cache-Control": "private, no-cache", "ETag": etag,
               "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
               "Vary": "Accept-Encoding"}
    if if_none_match and etag in [tag.strip() for tag in if_none_match.split(",")]:
        return Response(status_code=304, headers=headers)
    headers["Content-Security-Policy"] = csp
    if accepts_gzip(accept_encoding):
        body = compressed
        headers["Content-Encoding"] = "gzip"
    return HTMLResponse(body, headers=headers)
