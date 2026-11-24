from __future__ import annotations

import http.client
import http.server
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import passwords, paths  # noqa: E402
from styx.backend import tor_supervisor as tor


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"upstream-ok:" + self.headers.get("Host", "").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class GateHttp(unittest.TestCase):
    def test_login_then_proxy(self):
        up_port = _free_port()
        gate_port = _free_port()
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", up_port), _Handler)
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as raw:
                data = Path(raw)
                (data / "logs").mkdir()
                passwords.write_hash(data / "passwd", "cerberus-gate-99")
                parent = str(paths.PLUGIN_ROOT.parent)
                env = os.environ.copy()
                env["PYTHONPATH"] = parent + os.pathsep + env.get("PYTHONPATH", "")
                proc = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "styx.gate",
                        "--data-dir",
                        str(data),
                        "--upstream-host",
                        "127.0.0.1",
                        "--upstream-port",
                        str(up_port),
                        "--port",
                        str(gate_port),
                        "--bind",
                        "127.0.0.1",
                    ],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                try:
                    self._wait(gate_port)
                    # The old launcher remains identifiable after an update.
                    pidfile = paths.gate_pid_path(data)
                    tor.write_pid(pidfile, proc.pid, process=proc)
                    self.assertEqual(tor.read_pid(pidfile), proc.pid)
                    pidfile.write_text(str(proc.pid))
                    self.assertEqual(tor.read_pid(pidfile), proc.pid)
                    conn = http.client.HTTPConnection("127.0.0.1", gate_port, timeout=5)
                    conn.request("GET", "/login")
                    resp = conn.getresponse()
                    resp.read()
                    self.assertEqual(resp.status, 200)
                    csrf = None
                    for h, v in resp.getheaders():
                        if h.lower() == "set-cookie" and "styx_csrf=" in v:
                            csrf = v.split("styx_csrf=")[1].split(";")[0]
                    self.assertTrue(csrf)
                    body = urlencode({"csrf": csrf, "password": "cerberus-gate-99"})
                    conn.request(
                        "POST",
                        "/login",
                        body=body,
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Cookie": f"styx_csrf={csrf}",
                        },
                    )
                    resp2 = conn.getresponse()
                    resp2.read()
                    self.assertIn(resp2.status, (303, 302))
                    cookie = None
                    for h, v in resp2.getheaders():
                        if h.lower() == "set-cookie" and "styx_session=" in v:
                            cookie = v.split("styx_session=")[1].split(";")[0]
                    self.assertTrue(cookie)
                    conn.request("GET", "/", headers={"Cookie": f"styx_session={cookie}"})
                    resp3 = conn.getresponse()
                    payload = resp3.read().decode()
                    self.assertEqual(resp3.status, 200)
                    self.assertIn("upstream-ok:127.0.0.1:", payload)
                    conn.close()
                finally:
                    proc.terminate()
                    proc.wait(timeout=5)
                    proc.stdout.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            t.join(timeout=2)

    def _wait(self, port: int, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=0.2)
                s.close()
                return
            except OSError:
                time.sleep(0.1)
        self.fail("gate did not bind")


if __name__ == "__main__":
    unittest.main()
