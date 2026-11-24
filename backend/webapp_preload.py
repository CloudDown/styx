"""Speculative HTTP hints for the official renderer, never HTML rewriting."""

from __future__ import annotations

import asyncio
import json
import re
import time

import httpx

_MANIFEST = "/renderer-manifest.json"
_MAX_BYTES = 1024 * 1024
_REFRESH_SECONDS = 30
_ASSET = re.compile(r"assets/[A-Za-z0-9_-]{1,128}-[A-Za-z0-9_-]{8,32}\.(js|css)")


def launch_links(manifest: object) -> tuple[str, ...]:
    """Only the direct main entry and its CSS; never lazy pages or external URLs."""
    if not isinstance(manifest, dict):
        return ()
    entry = manifest.get("index.html")
    if not isinstance(entry, dict) or entry.get("isEntry") is not True:
        return ()
    imports = entry.get("dynamicImports")
    if not isinstance(imports, list) or "src/main.tsx" not in imports:
        return ()
    main = manifest.get("src/main.tsx")
    if not isinstance(main, dict) or main.get("isDynamicEntry") is not True:
        return ()
    script = main.get("file")
    if not isinstance(script, str) or not _ASSET.fullmatch(script) or not script.endswith(".js"):
        return ()
    links = [f"</{script}>; rel=modulepreload; crossorigin=anonymous"]
    styles = main.get("css")
    if isinstance(styles, list):
        for path in styles[:4]:
            if isinstance(path, str) and _ASSET.fullmatch(path) and path.endswith(".css"):
                link = f"</{path}>; rel=preload; as=style; crossorigin=anonymous"
                if link not in links:
                    links.append(link)
    return tuple(links)


class WebappPreload:
    """One bounded background manifest lookup per gate, never on the render path."""

    def __init__(self, client: httpx.AsyncClient, upstream: str):
        self.client = client
        self.url = upstream + _MANIFEST
        self.links: tuple[str, ...] = ()
        self._etag: str | None = None
        self._next = 0.0
        self._task: asyncio.Task[None] | None = None

    def warm(self) -> None:
        if self._task is not None and not self._task.done():
            return
        now = time.monotonic()
        if now >= self._next:
            self._next = now + _REFRESH_SECONDS
            self._task = asyncio.create_task(self._refresh())

    def current(self) -> tuple[str, ...]:
        # After the short validity window, skip rather than hint an older build.
        ready = self._task is not None and self._task.done() and time.monotonic() < self._next
        links = self.links if ready else ()
        self.warm()
        return links

    async def _refresh(self) -> None:
        previous = self.links
        self.links = ()
        headers = {"Accept-Encoding": "identity"}
        if self._etag:
            headers["If-None-Match"] = self._etag
        self._etag = None
        try:
            async with asyncio.timeout(2):
                async with self.client.stream("GET", self.url, headers=headers) as response:
                    if response.status_code == 304 and "If-None-Match" in headers:
                        self.links = previous
                        self._etag = headers["If-None-Match"]
                        return
                    if (response.status_code != 200 or "content-encoding" in response.headers or
                            "set-cookie" in response.headers or
                            response.headers.get("content-type", "").split(";")[0] != "application/json"):
                        return
                    data = bytearray()
                    async for chunk in response.aiter_raw():
                        if len(data) + len(chunk) > _MAX_BYTES:
                            return
                        data.extend(chunk)
                    self.links = launch_links(json.loads(data))
                    self._etag = response.headers.get("etag") if self.links else None
        except (TimeoutError, httpx.HTTPError, ValueError, RecursionError):
            # No hints on old/missing/malformed manifests. The official
            # renderer and launch flow still proceed exactly as before.
            return

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
