"""Interactive host setup through existing package managers, never in the gateway."""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


class SetupError(RuntimeError):
    pass


def _linux_install_command() -> list[str]:
    try:
        release = platform.freedesktop_os_release()
        family = set((release.get("ID", "") + " " + release.get("ID_LIKE", "")).split())
    except OSError:
        family = set()
    installers = {
        "pacman": ["-S", "--needed", "tor"],
        "apt-get": ["install", "tor"],
        "dnf": ["install", "tor"],
        "yum": ["install", "tor"],
        "zypper": ["install", "tor"],
        "apk": ["add", "tor"],
    }
    if family & {"arch", "manjaro"}:
        choices = ["pacman"]
    elif family & {"debian", "ubuntu"}:
        choices = ["apt-get"]
    elif family & {"fedora", "rhel", "centos"}:
        choices = ["dnf", "yum"]
    elif family & {"suse", "opensuse", "opensuse-tumbleweed", "opensuse-leap"}:
        choices = ["zypper"]
    elif "alpine" in family:
        choices = ["apk"]
    else:
        choices = [name for name in installers if shutil.which(name)]
        if len(choices) != 1:
            raise SetupError(
                "Cannot select the system package manager safely; install Tor manually."
            )
    for name in choices:
        executable = shutil.which(name)
        if executable:
            command = [executable, *installers[name]]
            if os.geteuid() == 0:
                return command
            elevate = shutil.which("sudo") or shutil.which("doas")
            if not elevate:
                raise SetupError("Tor installation needs sudo/doas or a system administrator.")
            return [elevate, *command]
    raise SetupError("The system package manager is unavailable; install Tor manually.")


def install_command() -> list[str]:
    if sys.platform == "linux":
        return _linux_install_command()
    if sys.platform == "darwin":
        brew = shutil.which("brew")
        if not brew:
            brew = next(
                (
                    p
                    for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew")
                    if os.path.isfile(p) and os.access(p, os.X_OK)
                ),
                None,
            )
        if brew:
            return [brew, "install", "tor"]
        raise SetupError("Install Homebrew first, or install Tor manually and set STYX_TOR_BINARY.")
    if sys.platform == "win32":
        # Scoop's main bucket provides the actual Tor Expert Bundle and hashes.
        scoop = shutil.which("scoop")
        if scoop:
            return [scoop, "install", "tor"]
        script = Path(os.environ.get("SCOOP") or Path.home() / "scoop") / "shims/scoop.ps1"
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        if script.is_file() and powershell:
            return [powershell, "-NoProfile", "-File", str(script), "install", "tor"]
        winget = shutil.which("winget")
        if winget:
            # winget has Tor Browser, not an Expert Bundle package. Make this
            # larger installation explicit and leave agreement prompts intact.
            return [
                winget,
                "install",
                "--exact",
                "--id",
                "TorProject.TorBrowser",
                "--source",
                "winget",
                "--scope",
                "user",
                "--interactive",
            ]
        raise SetupError(
            "Install Scoop/winget or the Tor Expert Bundle, then run hermes styx setup."
        )
    raise SetupError(f"Automatic Tor installation is not supported on {sys.platform}.")


def ensure_tor() -> str:
    from .tor_supervisor import tor_binary

    binary = tor_binary()
    if binary:
        return binary
    if os.environ.get("STYX_TOR_BINARY"):
        raise SetupError("STYX_TOR_BINARY is invalid; correct or unset it before running setup.")
    if not sys.stdin.isatty():
        raise SetupError("Tor is missing; run hermes styx setup in an interactive host terminal.")
    command = install_command()
    print("Tor is missing. Styx can install it through your package manager.")
    if "TorProject.TorBrowser" in command:
        print("winget will install the official Tor Browser, which includes the Tor executable.")
    print(
        "Command: "
        + (subprocess.list2cmdline(command) if sys.platform == "win32" else shlex.join(command))
    )
    print("The package manager may request administrator access and display agreement prompts.")
    try:
        approved = input("Proceed with this installation? [y/N] ").strip().casefold()
    except EOFError as exc:
        raise SetupError("Tor installation cancelled.") from exc
    if approved not in {"y", "yes", "o", "oui"}:
        raise SetupError("Tor installation cancelled; no package command was run.")
    # Inherit the terminal for sudo/UAC/package prompts. Never collect an admin
    # password, pipe a remote installer to a shell, or auto-accept agreements.
    try:
        result = subprocess.run(command, check=False)
    except OSError as exc:
        raise SetupError(f"Could not run the package manager: {exc}") from exc
    if result.returncode:
        raise SetupError(
            f"Tor installation failed (exit {result.returncode}); fix the package-manager error above."
        )
    binary = tor_binary()
    if not binary:
        raise SetupError(
            "The installer finished but Tor was not found; set STYX_TOR_BINARY to the installed "
            "tor/tor.exe path and retry. No onion service was started."
        )
    return binary
