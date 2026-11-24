"""Opt-in checks of the private-ish Hermes contracts Styx depends on.

These talk to a real, running Hermes Webapp and invoke its public CLI. They
are skipped by default because CI has no Hermes installation:

    STYX_HERMES_INTEGRATION=1 hermes --run-module unittest discover \
        -s ~/projet/styx/tests -p 'test_hermes_contracts.py' -v
"""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import supervisor, webapp_ensure  # noqa: E402
from styx.backend.network import require_loopback  # noqa: E402
from styx.backend.webapp_handoff import HandoffError, parse_launch_output  # noqa: E402
from styx.backend.webapp_preload import launch_links  # noqa: E402

_ENABLED = os.environ.get("STYX_HERMES_INTEGRATION") == "1"


@unittest.skipUnless(_ENABLED, "set STYX_HERMES_INTEGRATION=1 against a running Hermes Webapp")
class HermesContracts(unittest.TestCase):
    def setUp(self):
        if supervisor.target_name() != "webapp":
            self.skipTest("preload and native handoff only apply to target=webapp")
        self.host, self.port = supervisor.resolve_upstream()
        require_loopback(self.host)

    def _get(self, path: str) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            connection.request("GET", path, headers={"Origin": f"http://{self.host}:{self.port}"})
            response = connection.getresponse()
            return response.status, response.read(2 * 1024 * 1024)
        finally:
            connection.close()

    def test_renderer_manifest_still_exposes_the_main_module_and_styles(self):
        status, body = self._get("/renderer-manifest.json")
        self.assertEqual(status, 200, "run `hermes styx start` first")
        links = launch_links(json.loads(body))
        self.assertTrue(links, "manifest changed: no modulepreload/preload link was derived")
        self.assertTrue(any("rel=modulepreload" in link for link in links))
        self.assertTrue(any("as=style" in link for link in links))

    def test_public_webapp_cli_still_returns_a_parseable_launch_link(self):
        result = subprocess.run(
            webapp_ensure.hermes_argv() + ["webapp", "--no-open", "--skip-build"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=45,
            check=False,
        )
        self.assertEqual(result.returncode, 0, "hermes webapp --no-open failed")
        try:
            grant = parse_launch_output(result.stdout, self.host, self.port)
        except HandoffError as exc:
            self.fail(f"launch output contract changed: {exc}")
        if grant is None:
            self.skipTest("Hermes requires an additional sign-in provider")
        self.assertEqual(len(grant["ticket"]), 43)


if __name__ == "__main__":
    unittest.main()
