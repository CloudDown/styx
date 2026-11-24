"""hermes styx …"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import webapp_mode


def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="styx_command")
    subs.add_parser("status", help="Gate, Tor, onion, upstream")
    start = subs.add_parser("start", help="Start the Cerberus gate and publish the onion")
    start.add_argument(
        "--client-auth", action="store_true",
        help="Require a Tor client key (hermes styx client-auth) in addition to the password",
    )
    start.add_argument("--no-wait", action="store_true", help="Don't wait for the .onion hostname")
    setup = subs.add_parser("setup", help="Install missing Tor with confirmation, set a password and start")
    setup.add_argument("--client-auth", action="store_true", help="Require configured Tor client keys")
    setup.add_argument("--no-wait", action="store_true", help="Don't wait for the .onion hostname")
    subs.add_parser("stop", help="Stop gate and Tor")
    subs.add_parser("url", help="Print the onion URL (secret)")
    pw = subs.add_parser("passwd", help="Set the Cerberus passphrase")
    pw.add_argument("--password", help=argparse.SUPPRESS)
    ca = subs.add_parser("client-auth", help="Mint a Tor v3 client key")
    ca.add_argument("--name", default="device", help="Label for this client (default: device)")
    subs.add_parser("doctor", help="Check tor, passphrase, webapp, processes")
    webapp = subs.add_parser("webapp", help="Choose the default browser interface")
    webapp.add_argument("mode", nargs="?", choices=(*webapp_mode.MODES, "status"), default="status")
    subparser.set_defaults(func=styx_command)


def styx_command(args: argparse.Namespace) -> int:
    cmd = args.styx_command
    if not cmd:
        print("usage: hermes styx {setup,status,start,stop,url,passwd,client-auth,doctor,webapp}")
        return 2
    try:
        if cmd == "status":
            return _status()
        if cmd in {"start", "setup"}:
            return _start(
                client_auth=bool(getattr(args, "client_auth", False)),
                wait=not bool(getattr(args, "no_wait", False)),
            )
        if cmd == "stop":
            return _stop()
        if cmd == "url":
            return _url()
        if cmd == "passwd":
            return _passwd(getattr(args, "password", None))
        if cmd == "client-auth":
            return _client_auth(getattr(args, "name", "device"))
        if cmd == "doctor":
            return _doctor()
        if cmd == "webapp":
            return _webapp(args.mode)
    except KeyboardInterrupt:
        return 130
    print(f"unknown subcommand: {cmd}")
    return 2


def _webapp(mode: str) -> int:
    from . import paths

    try:
        root = paths.data_dir()
        if mode != "status":
            webapp_mode.write_mode(root, mode)
        print(f"webapp: {webapp_mode.read_mode(root)}")
        return 0
    except OSError as exc:
        print(f"styx: {exc}", file=sys.stderr)
        return 1


def _status() -> int:
    from .supervisor import status
    st = status()
    running = "up" if st["running"] else "down"
    print(f"styx          {running}")
    print(f"password      {'set' if st['password_set'] else 'MISSING — hermes styx passwd'}")
    print(f"tor           {st['tor_binary'] or 'NOT INSTALLED'}")
    print(f"gate          pid={st['gate_pid'] or '-'}  127.0.0.1:{st['gate_port']}")
    print(f"tor pid       {st['tor_pid'] or '-'}")
    print(f"target        {st['target']}  {st['upstream_host']}:{st['upstream_port']}  "
          f"{'ok' if st['upstream_ok'] else 'not listening'}")
    print(f"client-auth   {'on' if st['client_auth'] else 'off'}")
    if st.get("url"):
        print(f"url           {st['url']}")
    elif st["running"]:
        print("url           (publishing… retry hermes styx url)")
    else:
        print("url           —")
    return 0


def _start(*, client_auth: bool, wait: bool) -> int:
    from .supervisor import StyxError, start
    from .bootstrap import SetupError, ensure_tor
    from . import passwords, paths

    try:
        ensure_tor()
        if not passwords.read_hash(paths.passwd_path()):
            if not sys.stdin.isatty():
                raise SetupError("No passphrase set; run hermes styx setup in an interactive host terminal.")
            try:
                if _passwd(None):
                    return 1
            except EOFError as exc:
                raise SetupError("Password setup cancelled.") from exc
        st = start(wait=wait, client_auth=client_auth)
    except (StyxError, SetupError, OSError) as exc:
        print(f"styx: {exc}", file=sys.stderr)
        return 1
    print("styx started")
    if st.get("url"):
        print(st["url"])
        print("open in Tor Browser. Treat this URL as a secret.")
    else:
        print("hidden service is publishing; run hermes styx url in a minute")
    return 0


def _stop() -> int:
    from .supervisor import StyxError, stop
    try:
        stop()
    except StyxError as exc:
        print(f"styx: {exc}", file=sys.stderr)
        return 1
    print("styx stopped")
    return 0


def _url() -> int:
    from .supervisor import status
    st = status()
    url = st.get("url")
    if not url:
        print("styx: no onion yet (is it started?)", file=sys.stderr)
        return 1
    print(url)
    return 0


def _passwd(password: str | None) -> int:
    from . import passwords, paths
    if password is None:
        a = getpass.getpass("new passphrase: ")
        b = getpass.getpass("repeat: ")
        if a != b:
            print("styx: mismatch", file=sys.stderr)
            return 1
        password = a
    try:
        passwords.write_hash(paths.passwd_path(), password)
    except passwords.PassphraseError as exc:
        print(f"styx: {exc}", file=sys.stderr)
        return 1
    print("passphrase saved (scrypt). existing sessions are revoked; no gate restart needed.")
    return 0


def _client_auth(name: str) -> int:
    from . import client_auth, paths
    from .supervisor import status
    pub, priv = client_auth.generate_pair()
    dest = client_auth.write_server_auth(paths.data_dir(), name, pub)
    onion = status().get("onion") or "<your-onion>.onion"
    line = client_auth.client_line(str(onion), priv)
    print(f"server auth written: {dest}")
    print("add this in Tor Browser (onion client auth) or ClientOnionAuthDir:")
    print(line)
    print("then: hermes styx stop && hermes styx start --client-auth")
    return 0


def _doctor() -> int:
    from .supervisor import status
    st = status()
    checks = [
        ("tor binary", bool(st["tor_binary"]), st["tor_binary"] or "install tor"),
        ("passphrase", st["password_set"], "hermes styx passwd"),
        ("upstream", st["upstream_ok"], st.get("upstream_error") or f"nothing on {st['upstream_host']}:{st['upstream_port']}"),
        ("browser handoff", st["target"] != "webapp" or st.get("webapp_handoff", False), "hermes styx start"),
        ("gate process", bool(st["gate_pid"]), "hermes styx start"),
        ("tor process", bool(st["tor_pid"]), "hermes styx start"),
        ("onion", bool(st.get("onion")), "wait for publish / check logs"),
    ]
    rc = 0
    for name, ok, hint in checks:
        mark = "ok" if ok else "FAIL"
        extra = "" if ok else f"  ({hint})"
        print(f"  {mark:4}  {name}{extra}")
        if not ok:
            rc = 1
    return rc
