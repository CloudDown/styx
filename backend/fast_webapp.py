"""Styx Fast's static, authenticated browser shell and host-side mode choice."""

from __future__ import annotations

import base64
import gzip
import hashlib
from functools import lru_cache
from pathlib import Path

from starlette.responses import HTMLResponse, Response

from .asset_transfer import accepts_gzip
from .paths import PLUGIN_ROOT
from .storage import write_private

FAST = "/_styx/fast"
VIEW_QUERY = "_styx_view"
DEFAULT_MODE = "hermes"
MODES = (DEFAULT_MODE, "fast")
_FILES = PLUGIN_ROOT / "assets" / "fast"
MARKDOWN = FAST + "/marked-18.1.0.js"


def read_mode(root: Path) -> str:
    try:
        mode = (root / "webapp-mode").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return DEFAULT_MODE
    return mode if mode in MODES else DEFAULT_MODE


def write_mode(root: Path, mode: str) -> None:
    if mode not in MODES:
        raise ValueError("Unknown webapp mode")
    write_private(root / "webapp-mode", mode + "\n")


def _digest(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode()).digest()).decode("ascii")


@lru_cache(maxsize=1)
def _markdown_asset() -> tuple[bytes, bytes, str]:
    body = (_FILES / "vendor" / "marked-18.1.0.js").read_bytes()
    return body, gzip.compress(body, mtime=0), _digest(body.decode())


def markdown_response(accept_encoding: str) -> Response:
    raw, compressed, _ = _markdown_asset()
    headers = {"Vary": "Accept-Encoding", "Cache-Control": "private, max-age=86400",
               "X-Content-Type-Options": "nosniff"}
    if accepts_gzip(accept_encoding):
        raw = compressed
        headers["Content-Encoding"] = "gzip"
    return Response(raw, media_type="text/javascript", headers=headers)


@lru_cache(maxsize=1)
def _shell() -> tuple[bytes, bytes, str, str]:
    html = (_FILES / "index.html").read_text(encoding="utf-8")
    css = (_FILES / "app.css").read_text(encoding="utf-8")
    js = "\n".join((_FILES / name).read_text(encoding="utf-8") for name in
                   ("theme.js", "transcript.js", "composer.js", "app.js"))
    js = js.replace("__MARKED_INTEGRITY__", "sha256-" + _markdown_asset()[2])
    body = html.replace("<!-- STYX_STYLE -->", f"<style>{css}</style>", 1)
    body = body.replace("<!-- STYX_SCRIPT -->", f"<script>{js}</script>", 1).encode()
    csp = (f"default-src 'none'; script-src 'sha256-{_digest(js)}' 'strict-dynamic'; "
           f"style-src 'sha256-{_digest(css)}'; connect-src 'self'; media-src data:; "
           "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
    # Weak: valid for both the identity and gzip representations.
    etag = 'W/"' + base64.b16encode(hashlib.sha256(body).digest()[:16]).decode().lower() + '"'
    return body, gzip.compress(body, mtime=0), csp, etag


def response(accept_encoding: str, if_none_match: str = "") -> Response:
    body, compressed, csp, etag = _shell()
    # The shell carries no user data (the token lives in sessionStorage), so a
    # reload may revalidate instead of pulling 20+ kB again. `no-cache` still
    # forces the check; only an unchanged shell is answered with 304.
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
