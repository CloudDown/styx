"""Start/stop the Cerberus gate and the dedicated Tor process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import paths
from . import tor_supervisor as tor
from .network import port_open, require_loopback, upstream_health, wait_port
from .storage import write_private
from .platform_support import detached_process_options, lock_exclusive, private_dir


class StyxError(RuntimeError):
    pass


def _settings() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly
        cfg = load_config_readonly() or {}
        entry = ((cfg.get("plugins") or {}).get("entries") or {}).get("styx") or {}
        settings = entry.get("settings") or {}
    except Exception:
        settings = {}
    return settings if isinstance(settings, dict) else {}


def gate_port() -> int:
    try:
        return int(_settings().get("gate_port") or 9130)
    except (TypeError, ValueError):
        return 9130


def target_name() -> str:
    raw = str(_settings().get("target") or "webapp").strip().lower()
    return raw if raw in {"webapp", "dashboard"} else "webapp"


def resolve_upstream() -> tuple[str, int]:
    """Configured connect address. Does not enable or start anything."""
    from .webapp_ensure import apply_webapp_enable, dashboard_port

    host = "127.0.0.1"
    try:
        from hermes_cli.config import load_config_readonly
        cfg = load_config_readonly() or {}
    except Exception:
        cfg = {}
    if target_name() == "dashboard":
        block = cfg.get("dashboard") if isinstance(cfg.get("dashboard"), dict) else {}
        return require_loopback(block.get("host") or host), dashboard_port(cfg)
    updated, port, _ = apply_webapp_enable(cfg)
    return updated["webapp"]["host"], port


def read_state(data_dir: Path | None = None) -> dict[str, Any]:
    path = paths.state_path(data_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def write_state(data_dir: Path, payload: dict[str, Any]) -> None:
    dest = paths.state_path(data_dir)
    write_private(dest, json.dumps(payload, indent=2) + "\n")


def status(data_dir: Path | None = None) -> dict[str, Any]:
    root = data_dir or paths.data_dir()
    st = read_state(root)
    gate_pid = tor.read_pid(paths.gate_pid_path(root))
    tor_pid = tor.read_pid(paths.tor_pid_path(root))
    onion = tor.read_hostname(root)
    up_host, up_port = st.get("upstream_host") or "127.0.0.1", int(st.get("upstream_port") or 0)
    upstream_error = None
    if not up_port:
        try:
            up_host, up_port = resolve_upstream()
        except RuntimeError as exc:
            upstream_error = str(exc)
    upstream_ok, health_error = upstream_health(up_host, up_port)
    upstream_error = upstream_error or health_error
    from . import passwords as pw
    return {
        "running": bool(gate_pid and tor_pid),
        "gate_pid": gate_pid,
        "tor_pid": tor_pid,
        "gate_port": int(st.get("gate_port") or gate_port()),
        "onion": onion,
        "url": f"http://{onion}" if onion else None,
        "upstream_host": up_host,
        "upstream_port": up_port,
        "upstream_ok": upstream_ok,
        "upstream_error": upstream_error,
        "target": st.get("target") or target_name(),
        "password_set": pw.read_hash(paths.passwd_path(root)) is not None,
        "tor_binary": tor.tor_binary(),
        "client_auth": bool(st.get("client_auth")),
        "started_at": st.get("started_at"),
    }


def start(
    *,
    wait: bool = True,
    client_auth: bool = False,
    data_dir: Path | None = None,
    may_restart_gateway: bool = True,
) -> dict[str, Any]:
    root = data_dir or paths.data_dir()
    try:
        with _operation_lock(root):
            return _start_locked(root, wait=wait, client_auth=client_auth, may_restart_gateway=may_restart_gateway)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        raise StyxError(str(exc)) from exc


@contextmanager
def _operation_lock(root: Path):
    private_dir(root)
    fd = os.open(root / "supervisor.lock", os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        try:
            lock_exclusive(fd)
        except BlockingIOError as exc:
            raise StyxError("another Styx start/stop operation is in progress; retry shortly") from exc
        yield
    finally:
        os.close(fd)


def _start_locked(root: Path, *, wait: bool, client_auth: bool, may_restart_gateway: bool) -> dict[str, Any]:
    from . import passwords as pw
    from .webapp_ensure import ensure_upstream
    if not pw.read_hash(paths.passwd_path(root)):
        raise StyxError("no passphrase — run: hermes styx passwd")
    if not tor.tor_binary():
        raise StyxError("Tor is missing — install Tor and add it to PATH, or set STYX_TOR_BINARY (see README)")
    try:
        up_host, up_port = ensure_upstream(target_name(), may_restart=may_restart_gateway, data_dir=root)
    except RuntimeError as exc:
        raise StyxError(str(exc)) from exc
    current = status(root)
    gport = gate_port()
    if current["running"] and current.get("onion") and (
        current["gate_port"], current["upstream_host"], current["upstream_port"], current["client_auth"]
    ) == (gport, up_host, up_port, client_auth):
        return current
    if current["gate_pid"] or current["tor_pid"]:
        _stop_locked(root)

    if not 1 <= gport <= 65535 or gport == up_port:
        raise StyxError("gate_port must be 1..65535 and different from the upstream port")
    if port_open("127.0.0.1", gport):
        raise StyxError(f"gate port 127.0.0.1:{gport} is already occupied")
    try:
        gate_proc = _spawn_gate(root, up_host, up_port, gport)
        if not wait_port("127.0.0.1", gport, timeout=8.0) or gate_proc.poll() is not None:
            raise StyxError(f"gate did not bind 127.0.0.1:{gport} — see {paths.gate_log_path(root)}")
        tor.start_tor(root, gport, client_auth=client_auth)
        try:
            onion = tor.wait_for_hostname(root, timeout=90.0 if wait else 8.0)
        except tor.TorStartupTimeout:
            if wait:
                raise
            onion = None
        payload = {
            "gate_port": gport,
            "upstream_host": up_host,
            "upstream_port": up_port,
            "target": target_name(),
            "client_auth": client_auth,
            "started_at": datetime.now(UTC).isoformat(),
            "onion": onion,
        }
        write_state(root, payload)
    except BaseException:
        _stop_locked(root)
        raise
    return status(root)


def stop(data_dir: Path | None = None) -> None:
    root = data_dir or paths.data_dir()
    try:
        with _operation_lock(root):
            _stop_locked(root)
    except (RuntimeError, OSError) as exc:
        raise StyxError(str(exc)) from exc


def _stop_locked(root: Path) -> None:
    errors = []
    for path, name in [(paths.tor_pid_path(root), "tor"), (paths.gate_pid_path(root), "gate")]:
        try:
            tor.stop_pid(path, name=name)
        except (RuntimeError, OSError) as exc:
            errors.append(str(exc))
    if errors:
        raise StyxError("; ".join(errors))


def _spawn_gate(root: Path, up_host: str, up_port: int, gport: int) -> subprocess.Popen:
    parent = str(paths.PLUGIN_ROOT.parent)
    env = os.environ.copy()
    env["PYTHONPATH"] = parent + os.pathsep + env.get("PYTHONPATH", "")
    log = paths.gate_log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    pkg = paths.PLUGIN_ROOT.name
    with open(log, "ab", buffering=0) as log_f:
        proc = subprocess.Popen(
            [
                sys.executable, "-m", f"{pkg}.gate",
                "--data-dir", str(root),
                "--upstream-host", up_host,
                "--upstream-port", str(up_port),
                "--port", str(gport),
                "--bind", "127.0.0.1",
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            **detached_process_options(),
            close_fds=True,
            cwd=str(paths.PLUGIN_ROOT),
            env=env,
        )
    try:
        tor.write_pid(paths.gate_pid_path(root), proc.pid)
    except BaseException:
        tor.terminate_child(proc)
        raise
    return proc
