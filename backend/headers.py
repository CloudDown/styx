"""Header rewrite so the loopback Hermes listener accepts proxied onion traffic."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "http2-settings",
    }
)

# Hermes' DNS-rebinding guard rejects Host/Origin that are not the bind or
# public_url. The gate owns the .onion Host; upstream must see loopback.
_STRIP = HOP_BY_HOP | {
    "host",
    "origin",
    "referer",
    "content-length",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "forwarded",
}

_STYX_COOKIE_PREFIX = "styx_"


def _items(headers) -> list[tuple[str, str]]:
    # httpx.Headers.items() joins duplicates, including Set-Cookie.
    if hasattr(headers, "multi_items"):
        return list(headers.multi_items())
    if isinstance(headers, Mapping):
        return list(headers.items())
    return list(headers)


def _connection_headers(items: list[tuple[str, str]]) -> set[str]:
    return {
        token.strip().lower()
        for key, value in items
        if key.lower() == "connection"
        for token in value.split(",")
        if token.strip()
    }


def strip_styx_cookies(cookie_header: str) -> str:
    parts = []
    for piece in cookie_header.split(";"):
        name = piece.split("=", 1)[0].strip()
        if name.startswith(_STYX_COOKIE_PREFIX):
            continue
        stripped = piece.strip()
        if stripped:
            parts.append(stripped)
    return "; ".join(parts)


def outbound_headers(
    headers: Mapping[str, str] | Iterable[tuple[str, str]],
    *,
    upstream_host: str,
    upstream_port: int,
    websocket: bool = False,
) -> list[tuple[str, str]]:
    """Headers for the request we send to Hermes on loopback."""
    items = _items(headers)
    skip = _STRIP | _connection_headers(items)
    out: list[tuple[str, str]] = []
    for key, value in items:
        lk = key.lower()
        if lk in skip or lk.startswith("proxy-"):
            continue
        if websocket and lk.startswith("sec-websocket-"):
            continue
        if lk == "cookie":
            value = strip_styx_cookies(value)
            if not value:
                continue
        out.append((key, value))
    authority = _authority(upstream_host, upstream_port)
    # websockets generates Host and all handshake headers itself.
    if not websocket:
        out.append(("Host", authority))
    out.append(("Origin", f"http://{authority}"))
    return out


def inbound_response_headers(
    headers: Mapping[str, str] | Iterable[tuple[str, str]],
) -> list[tuple[str, str]]:
    items = _items(headers)
    # The response body is forwarded raw, so its encoding and length stay valid.
    skip = HOP_BY_HOP | _connection_headers(items)
    out: list[tuple[str, str]] = []
    for key, value in items:
        if key.lower() in skip:
            continue
        out.append((key, value))
    return out


def _authority(host: str, port: int) -> str:
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port == 80:
        return host
    return f"{host}:{port}"
