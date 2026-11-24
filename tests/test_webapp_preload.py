from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend.webapp_preload import WebappPreload, launch_links  # noqa: E402
from test_gate_regressions import Chunks  # noqa: E402


MANIFEST = {
    "index.html": {"isEntry": True, "dynamicImports": ["src/main.tsx"]},
    "src/main.tsx": {
        "isDynamicEntry": True, "file": "assets/main-12345678.js",
        "css": ["assets/main-abcdefgh.css", "https://remote.example/pay.css", "assets/main-abcdefgh.css"],
        "dynamicImports": ["admin"],
    },
    "admin": {"file": "assets/admin-12345678.js"},
}
LINKS = (
    "</assets/main-12345678.js>; rel=modulepreload; crossorigin=anonymous",
    "</assets/main-abcdefgh.css>; rel=preload; as=style; crossorigin=anonymous",
)


class PreloadManifest(unittest.IsolatedAsyncioTestCase):
    def test_only_official_hashed_entry_and_styles_are_eligible(self):
        self.assertEqual(launch_links(MANIFEST), LINKS)
        for bad_entry in ("//remote.example/x-y1234567.js", "../assets/main-12345678.js",
                          "assets/main-12345678.js>, <//remote.example/x>"):
            with self.subTest(entry=bad_entry):
                self.assertEqual(launch_links({
                    **MANIFEST, "src/main.tsx": {**MANIFEST["src/main.tsx"], "file": bad_entry},
                }), ())
        self.assertEqual(launch_links({"src/main.tsx": MANIFEST["src/main.tsx"]}), ())

    async def test_single_background_lookup_and_conditional_refresh(self):
        release = asyncio.Event()
        incoming = []

        async def serve(request):
            incoming.append(request)
            await release.wait()
            if request.headers.get("if-none-match") == '"fixture"':
                return httpx.Response(304)
            return httpx.Response(200, stream=Chunks(json.dumps(MANIFEST).encode()),
                                  headers={"ETag": '"fixture"', "Content-Type": "application/json"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
            preload = WebappPreload(client, "http://127.0.0.1:9120")
            self.addAsyncCleanup(preload.close)
            preload.warm()
            for _ in range(10):
                self.assertEqual(preload.current(), ())
            release.set()
            await preload._task
            self.assertEqual(preload.current(), LINKS)
            self.assertEqual(len(incoming), 1)
            self.assertEqual(incoming[0].url.path, "/renderer-manifest.json")
            self.assertNotIn("cookie", incoming[0].headers)
            preload._next = 0
            self.assertEqual(preload.current(), ())
            await preload._task
            self.assertEqual(len(incoming), 2)
            self.assertEqual(preload.current(), LINKS)

    async def test_rejects_missing_malformed_and_large_manifests(self):
        for status, body in ((404, b"not found"), (200, b"[broken"), (200, b" " * (1024 * 1024 + 1))):
            with self.subTest(status=status, size=len(body)):
                stream = Chunks(body)

                def serve(_):
                    return httpx.Response(status, stream=stream, headers={"Content-Type": "application/json"})

                async with httpx.AsyncClient(transport=httpx.MockTransport(serve)) as client:
                    preload = WebappPreload(client, "http://127.0.0.1:9120")
                    self.assertEqual(preload.current(), ())
                    await preload._task
                    self.assertEqual(preload.current(), ())
                    self.assertTrue(stream.closed)
