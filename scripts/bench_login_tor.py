"""Measure the Cerberus login page over a real Tor SOCKS proxy.

The gate itself has `SocksPort 0`; point this script at a Tor SOCKS port you
already trust (Tor Browser while open uses 9150, a standalone `tor` often 9050):

    python scripts/bench_login_tor.py --url "$(hermes styx url)" \
        --socks 127.0.0.1:9150 --runs 5

It fetches `/login`, then the painting fallback the page references, and with
`--login` also times the password POST. The onion address is never printed.

Requires `curl` with SOCKS5 support. No plugin dependency is imported.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode, urljoin

_CSRF = re.compile(r'name="csrf" value="([^"]+)"')
_PAINTING = re.compile(r'<img[^>]+src="([^"]+\.(?:avif|webp))"')
_WRITE_OUT = "%{http_code} %{time_total} %{size_download}"


def parse_csrf(html: str) -> str:
    match = _CSRF.search(html)
    if not match:
        raise ValueError("no CSRF field in the login page")
    return match.group(1)


def parse_painting_url(html: str) -> str:
    match = _PAINTING.search(html)
    if not match:
        raise ValueError("no painting fallback in the login page")
    return match.group(1)


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("no samples")
    return {"min": min(values), "median": statistics.median(values), "max": max(values)}


def _curl(
    args: list[str], *, stdin: bytes | None = None, timeout: float = 60.0
) -> tuple[int, float, int]:
    result = subprocess.run(
        ["curl", "-sS", "--max-time", str(int(timeout)), *args],
        input=stdin,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"curl failed with exit code {result.returncode}")
    try:
        code, seconds, size = result.stdout.decode("ascii").split()
        return int(code), float(seconds), int(size)
    except ValueError as exc:
        raise RuntimeError("unexpected curl output") from exc


def _fetch(
    url: str,
    socks: str,
    jar: Path,
    *,
    extra: list[str] | None = None,
    stdin: bytes | None = None,
    output: Path | None = None,
) -> tuple[int, float, int]:
    args = [
        "--socks5-hostname",
        socks,
        "--compressed",
        "--cookie",
        str(jar),
        "--cookie-jar",
        str(jar),
        "-o",
        str(output) if output else os.devnull,
        "-w",
        _WRITE_OUT,
        url,
    ]
    if extra:
        args[-1:-1] = extra
    return _curl(args, stdin=stdin)


def _error(prefix: str, exc: Exception) -> None:
    # Curl output can contain the URL; keep failures free of the address.
    print(f"{prefix}: {type(exc).__name__}: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("STYX_BENCH_URL", ""),
        help="Onion base URL (default: $STYX_BENCH_URL)",
    )
    parser.add_argument("--socks", required=True, help="Tor SOCKS5 host:port")
    parser.add_argument("--runs", type=int, default=3, help="Number of samples (default: 3)")
    parser.add_argument("--login", action="store_true", help="Also time the password POST")
    parser.add_argument(
        "--password-env",
        default="STYX_BENCH_PASSWORD",
        help="Environment variable holding the password (default: STYX_BENCH_PASSWORD)",
    )
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="Per-request timeout in seconds"
    )
    parser.add_argument("--json", type=Path, help="Write raw samples as JSON")
    args = parser.parse_args(argv)

    if not args.url:
        parser.error("--url or STYX_BENCH_URL is required")
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    base = args.url.rstrip("/") + "/"
    if subprocess.run(["curl", "--version"], capture_output=True, check=False).returncode:
        print("curl is required", file=sys.stderr)
        return 1

    password = None
    if args.login:
        password = os.environ.get(args.password_env) or getpass.getpass("Cerberus password: ")

    print(f"Measuring the login page over Tor (onion address redacted), {args.runs} run(s).")
    samples: list[dict[str, float]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="styx-bench-") as raw:
            jar = Path(raw) / "cookies.txt"
            for index in range(1, args.runs + 1):
                page = Path(raw) / f"login-{index}.html"
                code, seconds, size = _fetch(base + "login", args.socks, jar, output=page)
                if code != 200:
                    raise RuntimeError(f"login page returned HTTP {code}")
                html = page.read_text(encoding="utf-8", errors="replace")
                painting = urljoin(base, parse_painting_url(html))
                image_code, image_seconds, image_size = _fetch(painting, args.socks, jar)
                if image_code != 200:
                    raise RuntimeError(f"painting returned HTTP {image_code}")
                post_seconds = None
                if args.login:
                    csrf = parse_csrf(html)
                    form = urlencode({"csrf": csrf, "password": password, "next": "/"}).encode()
                    post_code, post_seconds, _ = _fetch(
                        base + "login",
                        args.socks,
                        jar,
                        extra=["--data-binary", "@-", "-X", "POST"],
                        stdin=form,
                    )
                    if post_code != 303:
                        raise RuntimeError(f"password POST returned HTTP {post_code}")
                samples.append(
                    {
                        "run": index,
                        "login_s": seconds,
                        "login_bytes": size,
                        "painting_s": image_seconds,
                        "painting_bytes": image_size,
                        "post_s": post_seconds,
                    }
                )
                print(
                    f"  run {index}: login {seconds:.2f}s / {size} B, "
                    f"painting {image_seconds:.2f}s / {image_size} B"
                    + (f", POST {post_seconds:.2f}s" if post_seconds is not None else "")
                )
    except (RuntimeError, ValueError, OSError) as exc:
        _error("benchmark failed", exc)
        return 1

    summary = {
        key: summarize([float(sample[key]) for sample in samples if sample[key] is not None])
        for key in ("login_s", "login_bytes", "painting_s", "painting_bytes", "post_s")
        if any(sample[key] is not None for sample in samples)
    }
    for key, stats in summary.items():
        print(
            f"{key}: min {stats['min']:.2f}, median {stats['median']:.2f}, max {stats['max']:.2f}"
        )
    if args.json:
        args.json.write_text(json.dumps(samples, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
