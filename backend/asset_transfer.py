"""Negotiated gzip for public, immutable JS/CSS only; never cache private data."""

from __future__ import annotations

import asyncio
import re
import zlib

import httpx


def accepts_gzip(value: str) -> bool:
    weights = {}
    for item in value.lower().split(","):
        name, *params = item.strip().split(";")
        weight = 1.0
        for param in params:
            if param.strip().startswith("q="):
                try:
                    weight = float(param.strip()[2:])
                except ValueError:
                    weight = 0.0
        weights[name] = weight if 0 <= weight <= 1 else 0.0
    return weights.get("gzip", weights.get("*", 0)) > 0


def compressible_asset(request, upstream: httpx.Response) -> bool:
    """Fail closed: dynamic pages, APIs, ranges and encoded bodies stay raw."""
    if request.method != "GET" or upstream.status_code != 200:
        return False
    if not re.fullmatch(r"/assets/[\w-]+-[A-Za-z0-9_-]{8,}\.(js|css)", request.url.path):
        return False
    if not accepts_gzip(request.headers.get("accept-encoding", "")):
        return False
    if any(name in request.headers for name in ("range", "if-range")):
        return False
    if any(name in upstream.headers for name in ("content-encoding", "content-range", "set-cookie")):
        return False
    directives = {part.strip().lower() for part in upstream.headers.get("cache-control", "").split(",")}
    if not {"public", "immutable"} <= directives or directives & {"private", "no-store", "no-transform"}:
        return False
    if "no-transform" in request.headers.get("cache-control", "").lower():
        return False
    vary = {part.strip().lower() for part in upstream.headers.get("vary", "").split(",") if part.strip()}
    if vary - {"origin", "accept-encoding"}:
        return False
    mime = upstream.headers.get("content-type", "").split(";")[0].lower()
    if mime not in {"text/javascript", "application/javascript", "text/css"}:
        return False
    try:
        return int(upstream.headers.get("content-length", "0")) >= 1024
    except ValueError:
        return False


async def gzip_stream(upstream: httpx.Response):
    compressor = zlib.compressobj(level=1, wbits=31)
    async for chunk in upstream.aiter_raw():
        # Keep compression off the event loop, including on small Pi CPUs.
        encoded = await asyncio.to_thread(compressor.compress, chunk)
        if encoded:
            yield encoded
    yield await asyncio.to_thread(compressor.flush)


def gzip_headers(raw_headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    # Validators/digests for the original bytes cannot describe the gzip bytes.
    skip = {b"content-length", b"accept-ranges", b"content-md5", b"digest",
            b"content-digest", b"repr-digest"}
    result = []
    for key, value in raw_headers:
        if key in skip:
            continue
        if key == b"etag" and not value.startswith(b"W/"):
            value = b"W/" + value
        result.append((key, value))
    result.extend([(b"content-encoding", b"gzip"), (b"vary", b"Accept-Encoding")])
    return result
