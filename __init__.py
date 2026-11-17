"""Styx — Tor onion front door for Hermes, behind Cerberus."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger("hermes_plugins.styx")


def register(ctx) -> None:
    from .cli import register_cli, styx_command

    ctx.register_cli_command(
        name="styx",
        help="Tor onion access to the Hermes web UI (Cerberus gate)",
        setup_fn=register_cli,
        handler_fn=styx_command,
        description=(
            "Publish the local Hermes webapp as a v3 onion service. "
            "Loopback only; password at the Cerberus gate. "
            "See: hermes styx doctor"
        ),
    )

    def _slash(_raw: str) -> str:
        from .supervisor import status
        st = status()
        if st["running"]:
            return "Styx is up. Onion URL is not sent in chat — run `hermes styx url` on the host."
        return "Styx is down. `hermes styx start` on the host."

    ctx.register_command(
        "styx",
        _slash,
        description="Styx onion gate status (does not print the URL)",
    )

    if ctx.get_config("autostart", default=False):
        threading.Thread(target=_autostart, name="styx-autostart", daemon=True).start()


def _autostart() -> None:
    try:
        from .supervisor import StyxError, start
        start(wait=False, may_restart_gateway=False)
        log.info("styx autostart: gate+tor launched")
    except StyxError as exc:
        log.warning("styx autostart skipped: %s", exc)
    except Exception:
        log.exception("styx autostart failed")
