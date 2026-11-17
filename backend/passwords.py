"""scrypt passphrase store. Stdlib only."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
from pathlib import Path

from .storage import write_private

# Modest params: a Pi 4 hashes this in well under a second; still not a toy.
_N = 2**14
_R = 8
_P = 1
_DKLEN = 32

_LINE = re.compile(
    r"^scrypt\$n=(?P<n>\d+)\$r=(?P<r>\d+)\$p=(?P<p>\d+)\$"
    r"(?P<salt>[A-Za-z0-9+/]+=*)\$(?P<dk>[A-Za-z0-9+/]+=*)\n?$"
)


class PassphraseError(ValueError):
    pass


def check_passphrase(password: str) -> None:
    if not password:
        raise PassphraseError("passphrase cannot be empty")
    if "\n" in password or "\r" in password:
        raise PassphraseError("passphrase cannot contain newlines")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    check_passphrase(password)
    salt_b = salt if salt is not None else os.urandom(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt_b, n=_N, r=_R, p=_P, dklen=_DKLEN,
    )
    return (
        f"scrypt$n={_N}$r={_R}$p={_P}$"
        f"{base64.b64encode(salt_b).decode()}$"
        f"{base64.b64encode(dk).decode()}"
    )


def verify_password(password: str, stored: str) -> bool:
    m = _LINE.match(stored.strip())
    if not m:
        return False
    try:
        salt = base64.b64decode(m["salt"])
        expected = base64.b64decode(m["dk"])
        n, r, p = int(m["n"]), int(m["r"]), int(m["p"])
    except (ValueError, TypeError):
        return False
    if n > 2**20 or r > 32 or p > 8 or len(salt) < 8:
        return False
    try:
        got = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected),
        )
    except (ValueError, OverflowError):
        return False
    return hmac.compare_digest(got, expected)


def write_hash(path: Path, password: str) -> None:
    write_private(path, hash_password(password) + "\n")


def read_hash(path: Path) -> str | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return raw.strip() or None
