"""Styx Fast: an isolated build of the official Hermes browser renderer."""

from __future__ import annotations

import base64
import gzip
import hashlib
import mimetypes
import re
import secrets
import shutil
import subprocess
import tempfile
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, Response

from .asset_transfer import accepts_gzip
from .paths import PLUGIN_ROOT
from .platform_support import lock_exclusive, private_dir
from .storage import write_private

FAST = "/_styx/fast"
APP = FAST + "/app"
VIEW_QUERY = "_styx_view"
DEFAULT_MODE = "hermes"
MODES = (DEFAULT_MODE, "fast", "tui")
_BUILD = PLUGIN_ROOT / "frontend" / "webapp-fast" / "build.mjs"
_GENERATION = re.compile(r"[a-f0-9]{24}")
_COMPRESSIBLE = re.compile(r"assets/[\w-]+-[A-Za-z0-9_-]{8,}\.(js|css)")
_FILE_TYPES = {
    ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
    ".wasm": "application/wasm", ".woff": "font/woff", ".woff2": "font/woff2",
    ".ttf": "font/ttf",
}
_MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".ico", ".mp3", ".wav", ".ogg", ".webm"}
_PUBLIC_FILES = {
    "apple-touch-icon.png", "nous-girl.png", "nous-girl-dark.png",
    "emojibase/en/data.json", "emojibase/en/messages.json", "emojibase/en/shortcodes/emojibase.json",
}
_PRIVATE = {"Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


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


def _builds(root: Path) -> Path:
    return root.resolve() / "fast-builds"


def current_build(root: Path) -> Path | None:
    try:
        generation = (root / "fast-build").read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    if _GENERATION.fullmatch(generation):
        directory = _builds(root) / generation
        if not directory.is_symlink() and (directory / "index.html").is_file():
            return directory
    return None


def build(root: Path, checkout: Path) -> None:
    """Publish a complete, immutable generation without modifying Hermes."""
    node = shutil.which("node")
    if not node:
        raise OSError("Node.js is required to compile Fast.")
    builds = private_dir(_builds(root))
    with (builds / ".lock").open("ab") as lock:
        lock_exclusive(lock.fileno())
        generation = secrets.token_hex(12)
        previous = current_build(root)
        with tempfile.TemporaryDirectory(dir=builds) as scratch:
            output = Path(scratch) / generation
            output.mkdir()
            try:
                subprocess.run([node, str(_BUILD), str(checkout), str(output), generation],
                               timeout=180, check=True)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                raise OSError("Fast build failed. The previous build (if any) is unchanged.") from None
            index = output / "index.html"
            if not index.is_file() or f"{FAST}/build/{generation}/assets/" not in index.read_text("utf-8"):
                raise OSError("Fast produced an incomplete browser build.")
            for asset in (output / "assets").iterdir():
                if asset.is_file() and _COMPRESSIBLE.fullmatch("assets/" + asset.name):
                    (asset.parent / (asset.name + ".gz")).write_bytes(gzip.compress(asset.read_bytes(), mtime=0))
            final = builds / generation
            output.rename(final)
            write_private(root / "fast-build", generation + "\n")
        # Keep the preceding generation for tabs already open during the build.
        for path in builds.iterdir():
            if path not in {previous, final} and _GENERATION.fullmatch(path.name) and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)


class _InlineScripts(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=False)
        self.script: list[str] | None = None
        self.hashes: list[str] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "script" and "src" not in dict(attrs):
            self.script = []

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            digest = hashlib.sha256("".join(self.script).encode()).digest()
            self.hashes.append(f"'sha256-{base64.b64encode(digest).decode('ascii')}'")
            self.script = None


# Fast and native intentionally share the same tab grant. The server cannot
# read it and the launch/exchange remains entirely Hermes-owned.
_LAUNCHER = r"""<!doctype html><meta charset="utf-8"><title>Hermes Fast</title>
<p>Connecting to Hermes Fast… <a href="/_styx/fast/connect">Continue</a></p>
<script>
const next = '/_styx/fast/';
let grant = '';
try { grant = sessionStorage.getItem(`hermes.webapp.session.v1:${JSON.stringify([location.origin, ''])}`); } catch {}
if (/^[A-Za-z0-9_-]{43}$/.test(grant || '')) {
  location.replace(next + 'app' + location.search + location.hash);
} else {
  const query = new URLSearchParams(location.search);
  const [prefix, id, ...rest] = location.hash.split('/');
  try {
    if (prefix === '#' && id && !rest.length && !id.includes('?')) query.set('session', decodeURIComponent(id));
  } catch {}
  location.replace(next + 'connect' + (query.size ? '?' + query : ''));
}
</script>"""
_MISSING = """<!doctype html><meta charset="utf-8"><title>Hermes Fast unavailable</title>
<p>Prepare Hermes Fast on the host with <code>hermes styx webapp fast</code>.</p>
<p><a href="/?_styx_view=hermes">Open full Hermes</a></p>"""


def _html(html: str, *, app: bool = False) -> Response:
    hashes = " ".join(_InlineScripts(html).hashes)
    script = f"'self' blob: 'wasm-unsafe-eval' {hashes}" if app else (hashes or "'none'")
    csp = (f"default-src 'none'; script-src {script}; script-src-attr 'none'; "
           "style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self' blob: data:; "
           "img-src 'self' data: blob:; media-src 'self' blob: data:; worker-src 'self' blob:; "
           "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
    return HTMLResponse(html, status_code=503 if html == _MISSING else 200, headers={
        **_PRIVATE, "Cache-Control": "no-store", "Content-Security-Policy": csp,
    })


@lru_cache(maxsize=2)
def _index(directory: Path) -> str:
    return (directory / "index.html").read_text(encoding="utf-8")


def response(root: Path, *, app: bool = False) -> Response:
    directory = current_build(root)
    if not directory:
        return _html(_MISSING)
    try:
        return _html(_index(directory), app=True) if app else _html(_LAUNCHER)
    except (OSError, UnicodeError):
        return _html(_MISSING)


def asset(root: Path, generation: str, rel: str, request: Request) -> Response:
    parts = rel.split("/")
    suffix = Path(rel).suffix
    mime = _FILE_TYPES.get(suffix) or (mimetypes.guess_type(rel)[0] if suffix in _MEDIA else None)
    if (not _GENERATION.fullmatch(generation) or not mime or
            (parts[0] != "assets" and rel not in _PUBLIC_FILES) or
            any(not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", part) for part in parts)):
        return Response(status_code=404)
    directory = _builds(root) / generation
    path = directory.joinpath(*parts)
    if not (directory / "index.html").is_file() or not path.is_file() or path.resolve() != path.absolute():
        return Response(status_code=404)
    headers = {**_PRIVATE, "Cache-Control": "private, max-age=31536000, immutable",
               "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; sandbox"}
    if _COMPRESSIBLE.fullmatch(rel):
        headers["Vary"] = "Accept-Encoding"
        original = path.stat()
        headers["ETag"] = f'W/"{generation}-{original.st_size:x}-{original.st_mtime_ns:x}"'
        variants = request.headers.get("if-none-match", "").split(",")
        if any(value.strip() in {"*", headers["ETag"], headers["ETag"][2:]} for value in variants):
            return Response(status_code=304, headers=headers)
        if (accepts_gzip(request.headers.get("accept-encoding", "")) and
                not any(name in request.headers for name in ("range", "if-range")) and
                "no-transform" not in request.headers.get("cache-control", "").lower()):
            compressed = path.with_name(path.name + ".gz")
            if compressed.is_file() and not compressed.is_symlink():
                path = compressed
                headers["Content-Encoding"] = "gzip"
    return FileResponse(path, media_type=mime, headers=headers)
