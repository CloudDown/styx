"""Small shared loopback and readiness helpers."""

from __future__ import annotations

import socket
import time
import http.client


def require_loopback(host: str) -> str:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise RuntimeError("refusing non-loopback host; configure 127.0.0.1")
    return host


def port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_port(host: str, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_open(host, port):
            return True
        time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
    return False


def upstream_health(host: str, port: int) -> tuple[bool, str | None]:
    """Check the served page, not merely an open TCP socket; never follow links."""
    try:
        require_loopback(host)
        if not 1 <= port <= 65535:
            return False, "upstream port is not configured"
        connection = http.client.HTTPConnection(host, port, timeout=2)
        try:
            connection.request("GET", "/", headers={"Origin": f"http://{connection.host}:{port}"})
            response = connection.getresponse()
            body = response.read(65536)
            if b"The Webapp is not built" in body or b"Hermes is unavailable" in body:
                return False, "Hermes interface is missing or stale; run hermes styx start"
            if not 200 <= response.status < 400:
                return False, f"upstream returned HTTP {response.status}"
            return True, None
        finally:
            connection.close()
    except (OSError, http.client.HTTPException, RuntimeError, ValueError):
        return False, "Hermes is not responding on the configured loopback port"
