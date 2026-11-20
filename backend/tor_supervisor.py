"""Dedicated Tor instance: write torrc, spawn, wait for the v3 hostname."""

from __future__ import annotations

import json
import errno
import os
import select
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil

from . import paths
from .platform_support import detached_process_options
from .storage import write_private

_IS_LINUX = sys.platform == "linux"
_TOR_ENV_KEYS = ("PATH", "HOME", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR")


class TorError(RuntimeError):
    pass


class TorStartupTimeout(TorError):
    pass


def tor_binary() -> str | None:
    configured = os.environ.get("STYX_TOR_BINARY")
    if configured:
        candidate = Path(configured).expanduser()
        return str(candidate.resolve()) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    if sys.platform == "win32":
        # Prefer the real executable, not Scoop's shim (which injects another
        # torrc and spawns a different PID).
        scoop = Path(os.environ.get("SCOOP") or Path.home() / "scoop")
        global_scoop = Path(os.environ.get("SCOOP_GLOBAL") or Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "scoop")
        for root in (scoop, global_scoop):
            executable = root / "apps/tor/current/tor/tor.exe"
            if executable.is_file():
                return str(executable.resolve())
    found = shutil.which("tor")
    if found:
        return found
    if sys.platform == "darwin":
        for raw in ("/opt/homebrew/bin/tor", "/usr/local/bin/tor"):
            if os.path.isfile(raw) and os.access(raw, os.X_OK):
                return raw
    if sys.platform == "win32":
        desktop = Path.home() / "Desktop"
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                desktop = Path(os.path.expandvars(winreg.QueryValueEx(key, "Desktop")[0]))
        except (ImportError, OSError):
            pass
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        for folder in (desktop / "Tor Browser", local / "Tor Browser",
                       local / "Programs/Tor Browser", Path.home() / "Tor Browser"):
            executable = folder / "Browser/TorBrowser/Tor/tor.exe"
            if executable.is_file():
                return str(executable.resolve())
    return None


def _tor_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if "\r" in value or "\n" in value:
        raise TorError("Tor state paths cannot contain newlines")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_torrc(
    *,
    data_dir: Path,
    gate_port: int,
    client_auth: bool,
) -> str:
    """Torrc for a hidden service that only exists to publish the gate.

    SocksPort 0: this instance is not a general proxy.
    HiddenServicePort 80 → 127.0.0.1:gate_port.
    """
    tor_dir = paths.tor_data_dir(data_dir)
    hs_dir = paths.hidden_service_dir(data_dir)
    lines = [
        f"DataDirectory {_tor_path(tor_dir)}",
        "SocksPort 0",
        "AvoidDiskWrites 0",
        "SafeLogging 1",
        # Log's filename parser does not unquote paths like DataDirectory does.
        # Popen already redirects stdout/stderr to our private tor.log.
        "Log notice stdout",
        f"HiddenServiceDir {_tor_path(hs_dir)}",
        "HiddenServiceVersion 3",
        f"HiddenServicePort 80 127.0.0.1:{int(gate_port)}",
    ]
    if client_auth:
        # Presence of authorized_clients/*.auth is what Tor v3 uses; we still
        # refuse to start if the dir is empty when this flag is on.
        lines.append("# client auth: files in HiddenServiceDir/authorized_clients/")
    return "\n".join(lines) + "\n"


def write_torrc(data_dir: Path, gate_port: int, client_auth: bool) -> Path:
    if client_auth:
        auth_dir = paths.authorized_clients_dir(data_dir)
        auths = list(auth_dir.glob("*.auth"))
        if not auths:
            raise TorError(
                "client-auth is on but authorized_clients/ is empty — "
                "run `hermes styx client-auth` first"
            )
    text = render_torrc(data_dir=data_dir, gate_port=gate_port, client_auth=client_auth)
    dest = paths.torrc_path(data_dir)
    write_private(dest, text)
    hs = paths.hidden_service_dir(data_dir)
    os.chmod(hs, 0o700)
    return dest


def start_tor(data_dir: Path, gate_port: int, *, client_auth: bool = False) -> subprocess.Popen:
    binary = tor_binary()
    if not binary:
        raise TorError(
            "Tor is missing: install tor (Linux), brew install tor (macOS), or the Tor Expert Bundle "
            "(Windows); put it on PATH or set STYX_TOR_BINARY to its full executable path"
        )
    torrc = write_torrc(data_dir, gate_port, client_auth)
    log = paths.tor_log_path(data_dir)
    log.parent.mkdir(parents=True, exist_ok=True)
    # Tor must not inherit Hermes provider credentials or profile settings.
    env = {key: value for key in _TOR_ENV_KEYS if (value := os.environ.get(key)) is not None}
    with open(log, "ab", buffering=0) as log_f:
        proc = subprocess.Popen(
            [binary, "-f", str(torrc)],
            stdin=subprocess.DEVNULL,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            env=env,
            **detached_process_options(),
            close_fds=True,
        )
    try:
        write_pid(paths.tor_pid_path(data_dir), proc.pid, process=proc)
    except BaseException:
        terminate_child(proc)
        raise
    return proc


def wait_for_hostname(data_dir: Path, timeout: float = 90.0) -> str:
    path = paths.hostname_path(data_dir)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not read_pid(paths.tor_pid_path(data_dir)):
            raise TorError(f"tor exited during startup — see {paths.tor_log_path(data_dir)}")
        if path.is_file():
            name = path.read_text(encoding="utf-8").strip()
            if name.endswith(".onion") and 56 <= len(name.split(".")[0]) <= 64:
                return name
        time.sleep(0.25)
    raise TorStartupTimeout(
        f"tor did not publish a hostname within {int(timeout)}s — see {paths.tor_log_path(data_dir)}"
    )


def read_hostname(data_dir: Path) -> str | None:
    path = paths.hostname_path(data_dir)
    try:
        name = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name if name.endswith(".onion") else None


def _process_info(pid: int, path: Path) -> dict | None:
    if _IS_LINUX:
        return _linux_process_info(pid, path)
    return _portable_process_info(pid, path)


def _matches_command(argv: list[str], path: Path) -> bool:
    root = path.parent.resolve()
    if path.name == "gate.pid":
        marker, expected = "--data-dir", root
        if not any(argv[i:i + 2] == ["-m", "styx.gate"] for i in range(len(argv) - 1)):
            return False
    elif path.name == "tor.pid" and Path(argv[0]).name.lower() in {"tor", "tor.exe"}:
        marker, expected = "-f", paths.torrc_path(root)
    else:
        return False
    index = argv.index(marker)
    return Path(argv[index + 1]).resolve() == expected


def _portable_process_info(pid: int, path: Path) -> dict | None:
    try:
        process = psutil.Process(pid)
        owner = process.username()
        if owner.casefold() != psutil.Process().username().casefold():
            return None
        if process.status() in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}:
            return None
        if not _matches_command(process.cmdline(), path) or not process.is_running():
            return None
        return {"pid": pid, "create_time": process.create_time(), "username": owner}
    except (psutil.Error, OSError, ValueError, IndexError):
        return None


def _linux_process_info(pid: int, path: Path) -> dict | None:
    """Match the service, profile, uid and Linux process birth identity."""
    if pid <= 0:
        return None
    try:
        proc = Path("/proc") / str(pid)
        if proc.stat().st_uid != os.getuid():
            return None
        fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        argv = (proc / "cmdline").read_bytes().decode().strip("\0").split("\0")
        if not _matches_command(argv, path):
            return None
        return {
            "pid": pid, "start_time": fields[19],
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        }
    except (OSError, ValueError, IndexError, UnicodeError):
        return None


def write_pid(path: Path, pid: int, *, process: subprocess.Popen | None = None) -> None:
    # Only registration of our newly spawned, unreaped child may wait for
    # /proc to settle around exec. Reads/stops still reject mismatches at once.
    deadline = time.monotonic() + 1.0
    while True:
        if process is not None and process.poll() is not None:
            log_path = paths.tor_log_path(path.parent) if path.name == "tor.pid" else paths.gate_log_path(path.parent)
            raise TorError(f"{path.stem} exited during startup (exit {process.returncode}) — see {log_path}")
        info = _process_info(pid, path)
        if info is not None:
            break
        if time.monotonic() >= deadline:
            raise TorError(f"cannot identify the process for {path.name} within 1s")
        time.sleep(0.01)
    write_private(path, json.dumps(info) + "\n")


def read_pid(path: Path) -> int | None:
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        pid = saved.get("pid") if isinstance(saved, dict) else saved
        if not isinstance(pid, int) or isinstance(pid, bool):
            return None
        live = _process_info(pid, path)
    except (OSError, ValueError):
        return None
    # Old integer-only pidfiles are accepted only after checking cmdline/uid.
    return pid if live and (isinstance(saved, int) or saved == live) else None


def stop_pid(path: Path, *, name: str = "process") -> None:
    pid = read_pid(path)
    if pid is None:
        path.unlink(missing_ok=True)
        return
    if not _IS_LINUX or not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        _stop_portable(path, pid, name)
        return
    try:
        fd = os.pidfd_open(pid)
    except ProcessLookupError:
        path.unlink(missing_ok=True)
        return
    except OSError as exc:
        if exc.errno in {errno.ENOSYS, errno.EINVAL}:
            _stop_portable(path, pid, name)
            return
        raise TorError(f"cannot safely stop {name}: Linux pidfd support is required") from exc
    try:
        # The fd pins this exact process, so PID reuse cannot redirect a signal.
        if read_pid(path) == pid:
            poll = select.poll()
            poll.register(fd, select.POLLIN)
            try:
                signal.pidfd_send_signal(fd, signal.SIGTERM)
                if not poll.poll(4000):
                    signal.pidfd_send_signal(fd, signal.SIGKILL)
                    if not poll.poll(1000):
                        raise TorError(f"{name} did not stop")
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
        path.unlink(missing_ok=True)
    finally:
        os.close(fd)


def _stop_portable(path: Path, pid: int, name: str) -> None:
    try:
        process = psutil.Process(pid)
        # psutil's signalling methods check its cached creation time against
        # PID reuse; never use os.kill(pid, 0), which terminates on Windows.
        if read_pid(path) == pid and process.is_running():
            process.terminate()
            try:
                process.wait(timeout=4)
            except psutil.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        path.unlink(missing_ok=True)
    except psutil.NoSuchProcess:
        path.unlink(missing_ok=True)
    except psutil.Error as exc:
        raise TorError(f"cannot safely stop {name}: {type(exc).__name__}") from exc


def terminate_child(proc: subprocess.Popen) -> None:
    """Rollback a child which failed before its pidfile could be recorded."""
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=4)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=4)
