"""Negotiated compression for public, immutable JS/CSS only; no shared cache."""

from __future__ import annotations

import asyncio
import re
import zlib
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from starlette.requests import Request

try:
    from compression import zstd
except ImportError:  # Python < 3.14 and runtimes without the optional module.
    zstd = None


def _encoding_weights(value: str) -> dict[str, float]:
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
    return weights


def accepts_gzip(value: str) -> bool:
    weights = _encoding_weights(value)
    return weights.get("gzip", weights.get("*", 0)) > 0


def _transformable(request: Request, upstream: httpx.Response) -> bool:
    """Fail closed: dynamic pages, APIs, ranges and encoded bodies stay raw."""
    if request.method != "GET" or upstream.status_code != 200:
        return False
    if not re.fullmatch(r"/assets/[\w-]+-[A-Za-z0-9_-]{8,}\.(js|css)", request.url.path):
        return False
    if any(name in request.headers for name in ("range", "if-range")):
        return False
    if any(
        name in upstream.headers for name in ("content-encoding", "content-range", "set-cookie")
    ):
        return False
    directives = {
        part.strip().lower() for part in upstream.headers.get("cache-control", "").split(",")
    }
    if not {"public", "immutable"} <= directives or directives & {
        "private",
        "no-store",
        "no-transform",
    }:
        return False
    if "no-transform" in request.headers.get("cache-control", "").lower():
        return False
    vary = {
        part.strip().lower() for part in upstream.headers.get("vary", "").split(",") if part.strip()
    }
    if vary - {"origin", "accept-encoding"}:
        return False
    mime = upstream.headers.get("content-type", "").split(";")[0].lower()
    if mime not in {"text/javascript", "application/javascript", "text/css"}:
        return False
    try:
        return int(upstream.headers.get("content-length", "0")) >= 1024
    except ValueError:
        return False


def asset_encoding(
    request: Request, upstream: httpx.Response, *, prefer_zstd: bool = False
) -> str | None:
    if not _transformable(request, upstream):
        return None
    weights = _encoding_weights(request.headers.get("accept-encoding", ""))
    gzip = weights.get("gzip", weights.get("*", 0))
    # Older browsers can advertise * without supporting zstd.
    modern = weights.get("zstd", 0)
    if prefer_zstd and zstd is not None and modern > 0 and modern >= gzip:
        return "zstd"
    return "gzip" if gzip > 0 else None


async def compressed_stream(
    upstream: httpx.Response, encoding: str, *, gzip_level: int = 1
) -> AsyncIterator[bytes]:
    if encoding == "zstd":
        compressor = zstd.ZstdCompressor(
            options={
                zstd.CompressionParameter.compression_level: 8,
                # Below the 8 MiB maximum decoder window in HTTP zstd.
                zstd.CompressionParameter.window_log: 22,
            }
        )
    else:
        compressor = zlib.compressobj(level=gzip_level, wbits=31)
    async for chunk in upstream.aiter_raw():
        # Keep compression off the event loop, including on small Pi CPUs.
        encoded = await asyncio.to_thread(compressor.compress, chunk)
        if encoded:
            yield encoded
    yield await asyncio.to_thread(compressor.flush)


def encoding_headers(
    raw_headers: list[tuple[bytes, bytes]], encoding: str
) -> list[tuple[bytes, bytes]]:
    # Validators/digests for the original bytes cannot describe the new bytes.
    skip = {
        b"content-length",
        b"accept-ranges",
        b"content-md5",
        b"digest",
        b"content-digest",
        b"repr-digest",
    }
    result = []
    for key, value in raw_headers:
        if key in skip:
            continue
        if key == b"etag" and not value.startswith(b"W/"):
            value = b"W/" + value
        result.append((key, value))
    result.extend([(b"content-encoding", encoding.encode("ascii")), (b"vary", b"Accept-Encoding")])
    return result
