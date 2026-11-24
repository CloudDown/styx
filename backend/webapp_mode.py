"""Select the official Webapp or the browser terminal."""

from pathlib import Path

from .storage import write_private

VIEW_QUERY = "_styx_view"
DEFAULT_MODE = "hermes"
MODES = (DEFAULT_MODE, "tui")


def read_mode(root: Path) -> str:
    try:
        mode = (root / "webapp-mode").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return DEFAULT_MODE
    return mode if mode in MODES else DEFAULT_MODE


def write_mode(root: Path, mode: str) -> None:
    if mode not in MODES:
        raise ValueError("Unknown webapp mode")
    write_private(root / "webapp-mode", mode + "\n")
