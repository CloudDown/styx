"""Turn the Hermes webapp on and make sure the gateway is serving it.

Styx owns remote auth (Cerberus). The webapp stays loopback; no public_url is set.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .network import port_open, require_loopback, upstream_health, wait_port


def apply_webapp_enable(cfg: dict[str, Any]) -> tuple[dict[str, Any], int, bool]:
    """Set webapp.enabled true in a config mapping. Does not write disk."""
    out = dict(cfg)
    block = dict(out.get("webapp") or {}) if isinstance(out.get("webapp"), dict) else {}
    require_loopback(block.get("host") or "127.0.0.1")
    try:
        port = int(block.get("port") or 9120)
    except (TypeError, ValueError):
        port = 9120
    changed = False
    if block.get("enabled") is not True:
        block["enabled"] = True
        changed = True
    if not block.get("host"):
        block["host"] = "127.0.0.1"
        changed = True
    if "port" not in block:
        block["port"] = port
        changed = True
    out["webapp"] = block
    return out, port, changed


def dashboard_port(cfg: dict[str, Any]) -> int:
    dash = cfg.get("dashboard") if isinstance(cfg.get("dashboard"), dict) else {}
    try:
        return int(dash.get("port") or 9119)
    except (TypeError, ValueError):
        return 9119


def hermes_argv() -> list[str]:
    found = shutil.which("hermes")
    return [found] if found else [sys.executable, "-m", "hermes_cli.main"]


def ensure_upstream(target: str, *, may_restart: bool = True, data_dir: Path | None = None) -> tuple[str, int]:
    """Return (127.0.0.1, port) of a live upstream, enabling/restarting as needed.

    Raises RuntimeError with a user-facing message.
    """
    from hermes_cli.config import load_config, load_config_readonly, save_config

    connect = "127.0.0.1"
    cfg = load_config_readonly() or {}
    if target == "dashboard":
        block = cfg.get("dashboard") if isinstance(cfg.get("dashboard"), dict) else {}
        connect = require_loopback(block.get("host") or connect)
        port = dashboard_port(cfg)
        if port_open(connect, port):
            _wait_healthy(connect, port)
            return connect, port
        raise RuntimeError(
            f"dashboard not listening on {connect}:{port} — start it once "
            f"(hermes dashboard --no-open) or keep target=webapp"
        )

    live = load_config()
    updated, port, changed = apply_webapp_enable(live)
    connect = updated["webapp"]["host"]
    if changed:
        save_config(updated, merge_existing=True)

    # The public CLI owns freshness receipts, toolchains and packaged bundles.
    # --build-only never opens a browser, emits a sign-in link or restarts bots.
    _prepare_webapp(data_dir)
    if port_open(connect, port):
        _wait_healthy(connect, port)
        return connect, port
    if not may_restart:
        if not wait_port(connect, port, timeout=90.0):
            raise RuntimeError("webapp.enabled is on; this gateway boot has no listener yet")
        _wait_healthy(connect, port)
        return connect, port

    _bring_up_gateway(connect, port)
    if not wait_port(connect, port, timeout=90.0):
        raise RuntimeError(
            f"webapp did not bind {connect}:{port} after enabling it — "
            f"check `hermes gateway status`"
        )
    _wait_healthy(connect, port)
    return connect, port


def _prepare_webapp(data_dir: Path | None) -> None:
    from . import paths

    root = data_dir or paths.data_dir()
    log_path = root / "logs" / "webapp-build.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("ab") as log:
            result = subprocess.run(
                hermes_argv() + ["webapp", "--build-only"],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                timeout=900, check=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"webapp build timed out after 15 minutes — see {log_path}") from exc
    if result.returncode:
        raise RuntimeError(
            f"Hermes could not prepare its webapp (exit {result.returncode}) — see {log_path}; "
            "check the Hermes Node/build-tool installation"
        )


def _wait_healthy(host: str, port: int) -> None:
    deadline = time.monotonic() + 20
    while True:
        healthy, error = upstream_health(host, port)
        if healthy:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(error or "Hermes interface is not ready")
        time.sleep(0.25)


def _bring_up_gateway(host: str, port: int) -> None:
    env = os.environ.copy()
    cmd = hermes_argv()
    subprocess.run(
        cmd + ["gateway", "ensure", "--timeout", "60"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=90,
        check=False,
    )
    if wait_port(host, port, timeout=8.0):
        return
    subprocess.run(
        cmd + ["gateway", "restart", "--interrupt", "--detach"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=90,
        check=False,
    )
