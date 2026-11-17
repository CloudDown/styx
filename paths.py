"""Plugin paths. Data lives in Hermes plugin-data, never in the install dir."""

from __future__ import annotations

from pathlib import Path

from .platform_support import private_dir

PLUGIN_ID = "styx"
PLUGIN_ROOT = Path(__file__).resolve().parent


def data_dir() -> Path:
    """Profile-scoped durable dir (survives plugin update/remove of the code)."""
    from plugins.plugin_storage import plugin_data_dir

    root = plugin_data_dir(PLUGIN_ID)
    private_dir(root)
    (root / "logs").mkdir(exist_ok=True)
    (root / "tor").mkdir(exist_ok=True)
    private_dir(root / "hidden_service")
    return root


def passwd_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "passwd"


def session_key_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "session.key"


def state_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "state.json"


def tor_data_dir(root: Path | None = None) -> Path:
    return (root or data_dir()) / "tor"


def hidden_service_dir(root: Path | None = None) -> Path:
    d = (root or data_dir()) / "hidden_service"
    private_dir(d)
    return d


def authorized_clients_dir(root: Path | None = None) -> Path:
    d = hidden_service_dir(root) / "authorized_clients"
    private_dir(d)
    return d


def hostname_path(root: Path | None = None) -> Path:
    return hidden_service_dir(root) / "hostname"


def torrc_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "torrc"


def gate_pid_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "gate.pid"


def tor_pid_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "tor.pid"


def gate_log_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "logs" / "gate.log"


def tor_log_path(root: Path | None = None) -> Path:
    return (root or data_dir()) / "logs" / "tor.log"
