"""HMAC session cookies for the Cerberus gate."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from .platform_support import private_dir
from .storage import write_private

COOKIE = "styx_session"
CSRF_COOKIE = "styx_csrf"
TTL_SECONDS = 12 * 60 * 60


def load_or_create_key(path: Path) -> bytes:
    private_dir(path.parent)
    if path.is_file():
        key = path.read_bytes()
        if len(key) >= 32:
            return key
    key = os.urandom(32)
    write_private(path, key)
    return key


def issue(secret: bytes, *, ttl: int = TTL_SECONDS) -> str:
    exp = int(time.time()) + ttl
    nonce = secrets.token_urlsafe(16)
    body = f"{exp}.{nonce}"
    sig = hmac.new(secret, body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def password_key(secret: bytes, stored: str) -> bytes:
    """Bind sessions to the current salted password hash, without rehashing."""
    return hmac.digest(secret, b"styx-password-session\0" + stored.encode("utf-8"), "sha256")


def valid(secret: bytes, token: str | None) -> bool:
    if not token or len(token) > 256 or not token.isascii() or token.count(".") != 2:
        return False
    exp_s, nonce, sig = token.split(".", 2)
    body = f"{exp_s}.{nonce}"
    expect = hmac.new(secret, body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return False
    try:
        exp = int(exp_s)
    except ValueError:
        return False
    return exp >= int(time.time())


class Revocations:
    """Bounded logout deny-list; session tokens are otherwise stateless."""

    def __init__(self, max_entries: int = 1024) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max = max_entries
        self._until: dict[bytes, float] = {}

    @staticmethod
    def _key(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8", "replace")).digest()

    def revoke(self, token: str | None) -> None:
        if not token:
            return
        now = time.time()
        self._until[self._key(token)] = now + TTL_SECONDS
        self._prune(now)

    def contains(self, token: str | None) -> bool:
        if not token:
            return False
        key = self._key(token)
        until = self._until.get(key)
        if until is None:
            return False
        if until < time.time():
            self._until.pop(key, None)
            return False
        return True

    def _prune(self, now: float) -> None:
        for key, until in list(self._until.items()):
            if until < now:
                del self._until[key]
        while len(self._until) > self._max:
            self._until.pop(next(iter(self._until)))


def new_csrf() -> str:
    return secrets.token_urlsafe(24)
