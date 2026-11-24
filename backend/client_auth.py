"""Tor v3 onion client authorization (x25519). Optional extra lock besides the password."""

from __future__ import annotations

import base64
import re
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from . import paths

_B32_STRIP = re.compile(r"=+$")


def _b32(raw: bytes) -> str:
    return _B32_STRIP.sub("", base64.b32encode(raw).decode("ascii")).lower()


def generate_pair() -> tuple[str, str]:
    """Return (public_b32, private_b32) for descriptor:x25519."""
    priv = X25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    priv_raw = priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return _b32(pub), _b32(priv_raw)


def write_server_auth(data_dir: Path, name: str, public_b32: str) -> Path:
    dest = paths.authorized_clients_dir(data_dir) / f"{_safe(name)}.auth"
    dest.write_text(f"descriptor:x25519:{public_b32}\n", encoding="utf-8")
    dest.chmod(0o600)
    return dest


def client_line(onion: str, private_b32: str) -> str:
    host = onion.strip().removeprefix("http://").removeprefix("https://").split("/")[0]
    return f"{host}:descriptor:x25519:{private_b32}"


def _safe(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()) or "client"
    return cleaned[:64]
