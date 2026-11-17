"""Use Hermes' public one-use browser launch flow after Cerberus authentication."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
import subprocess
import time
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit

from .webapp_ensure import hermes_argv

ENTRY_QUERY = "_styx_entry"
_ENTRY_TTL = 120
_MAX_ENTRIES = 128
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


class HandoffError(RuntimeError):
    pass


def strip_entry_query(query: str) -> str:
    return urlencode([(key, value) for key, value in parse_qsl(query, keep_blank_values=True)
                      if key != ENTRY_QUERY])


def parse_launch_output(output: str, host: str, port: int) -> dict[str, str] | None:
    if len(output) > 131072:
        raise HandoffError("Hermes returned an unexpected browser-launch response.")
    # An explicitly configured Hermes sign-in provider is not bypassed.
    if any(line.startswith("Open the Webapp and sign in with your dashboard account:")
           for line in output.splitlines()):
        return None
    for line in output.splitlines():
        value = line.strip()
        if not value.startswith(("http://", "https://")):
            continue
        try:
            url = urlsplit(value)
            if (url.scheme != "http" or url.hostname != host or (url.port or 80) != port
                    or url.username is not None or url.password is not None
                    or url.path != "/webapp/launch" or url.query):
                raise ValueError("unexpected origin or path")
            params = parse_qs(url.fragment, keep_blank_values=True, max_num_fields=8)
            tickets = params.get("ticket", [])
            if (set(params) - {"ticket", "query"} or len(tickets) != 1
                    or not _TOKEN.fullmatch(tickets[0]) or len(params.get("query", [])) > 1):
                raise ValueError("unexpected ticket")
            return {"ticket": tickets[0], "query": params.get("query", [""])[0]}
        except ValueError:
            # Never include CLI output, URLs or tickets in errors/logs.
            raise HandoffError("Hermes supplied an incompatible browser launch link.") from None
    raise HandoffError("Hermes did not supply a private browser launch link.")


def request_launch(host: str, port: int) -> dict[str, str] | None:
    try:
        result = subprocess.run(
            hermes_argv() + ["webapp", "--no-open", "--skip-build"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, timeout=45, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise HandoffError("Hermes browser launch failed; retry or check Hermes on the host.") from None
    if result.returncode:
        raise HandoffError("Hermes refused the browser launch; check Hermes on the host.")
    return parse_launch_output(result.stdout, host, port)


class WebappHandoff:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self._entries: dict[str, tuple[float, bytes]] = {}
        self._slots = asyncio.Semaphore(2)

    def _prune(self) -> None:
        now = time.monotonic()
        self._entries = {key: value for key, value in self._entries.items() if value[0] > now}

    def consume(self, entry: str | None, session: str) -> bool:
        self._prune()
        saved = self._entries.get(entry or "")
        if not saved or not hmac.compare_digest(saved[1], hashlib.sha256(session.encode()).digest()):
            return False
        del self._entries[entry]
        return True

    async def launch(self, session: str, query: str) -> str | None:
        self._prune()
        if len(self._entries) >= _MAX_ENTRIES:
            raise HandoffError("Too many pending browser launches; retry shortly.")
        try:
            async with asyncio.timeout(5):
                await self._slots.acquire()
        except TimeoutError:
            raise HandoffError("Hermes browser launch is busy; retry shortly.") from None
        try:
            work = asyncio.create_task(asyncio.to_thread(request_launch, self.host, self.port))
            cancelled = False
            while True:
                try:
                    grant = await asyncio.shield(work)
                    break
                except asyncio.CancelledError:
                    if work.cancelled():
                        raise
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
        finally:
            self._slots.release()
        if grant is None:
            return None
        self._prune()
        if len(self._entries) >= _MAX_ENTRIES:
            raise HandoffError("Too many pending browser launches; retry shortly.")
        entry = secrets.token_urlsafe(24)
        requested = parse_qsl(strip_entry_query(query), keep_blank_values=True)
        requested_keys = {key for key, _ in requested}
        defaults = [(key, value) for key, value in parse_qsl(grant["query"].lstrip("?"), keep_blank_values=True)
                    if key != ENTRY_QUERY and key not in requested_keys]
        target_query = urlencode(defaults + requested + [(ENTRY_QUERY, entry)])
        self._entries[entry] = (time.monotonic() + _ENTRY_TTL, hashlib.sha256(session.encode()).digest())
        # Only a relative, same-origin redirect. The real credential never
        # enters a URL: Hermes exchanges the one-use fragment for sessionStorage.
        return "/webapp/launch#" + urlencode({"ticket": grant["ticket"], "query": target_query})
