<h1 align="center">Styx</h1>
<p align="center">Access your Hermes web UI through Tor Browser.<br>One onion address, one password. No ports exposed to your local network.</p>

<p align="center"><img src="docs/login.png" width="100%" alt="Styx login page: a password field over a mythological painting, with Cerberus by the river Styx." /></p>

## Install

On the machine running Hermes, you need **Hermes ≥ 0.22.0**, Git and **Tor**. The plugin targets Linux, macOS and native Windows; Linux is tested locally, while native macOS/Windows validation runs through the added CI matrix. Use [Tor Browser](https://www.torproject.org/) to connect.

Install Tor with `apt install tor` / `pacman -S tor` on Linux, `brew install tor` on macOS, or the **Tor Expert Bundle** on Windows. Put `tor` / `tor.exe` on `PATH`, or set `STYX_TOR_BINARY` to its full executable path. Styx does not silently install system packages or download Tor.

```bash
mkdir -p "${HERMES_HOME:-$HOME/.hermes}/plugins"
git clone https://github.com/CloudDown/styx.git "${HERMES_HOME:-$HOME/.hermes}/plugins/styx"
hermes plugins enable styx
```

On Windows (PowerShell), use:

```powershell
$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $HOME ".hermes" }
New-Item -ItemType Directory -Force (Join-Path $HermesHome "plugins")
git clone https://github.com/CloudDown/styx.git (Join-Path $HermesHome "plugins/styx")
hermes plugins enable styx
```

Windows state must be on a filesystem supporting private ACLs (normally NTFS). The manifest declares `psutil`, already included in current Hermes, for portable process management.

## 1. Set a password

```bash
hermes styx passwd
```

Cerberus guards access to the interface. Choose a long, unique passphrase.

## 2. Open the passage

```bash
hermes styx start
hermes styx url
```

Styx asks Hermes to prepare the webapp (reusing a fresh bundle or building a missing/outdated one), enables it, and starts or restarts the gateway if needed. It checks the actual HTTP response, not merely an open port. Copy the displayed address **into Tor Browser**, then enter your password. Keep the host machine awake; Tor can add latency.

Rebuilding an interface on a running gateway does not restart Hermes or its bots. Build errors point to `plugin-data/styx/logs/webapp-build.log`; startup does not report success with a missing-interface error page.

Your address stays the same across stops and restarts. Keep it private, even though a password is still required to get in.

## 3. Close it

```bash
hermes styx stop
```

Only Tor and Cerberus stop. Hermes and its bots keep running.

## Everyday use

| Action | Command |
|---|---|
| Check status on the host | `hermes styx status` |
| Diagnose a problem | `hermes styx doctor` |
| Change your password | `hermes styx passwd` |
| Check from chat without revealing the address | `/styx` |

The dashboard's **Styx** tab also lets you start, stop and copy the address. The Desktop status chip is opt-in, under **Capabilities → Plugins**.

To require a per-device Tor key in addition to the password, see the [guide (French)](docs/GUIDE.md#clé-tor-par-appareil).

## Access and privacy

A session grants the permissions of the OS user running Hermes, **including shell access, files and keys**. Only share access with someone you would trust with that account.

Hermes and Cerberus listen only on loopback. Tor publishes the entry point; no port is exposed to the LAN. The login page loads no external resources. Login attempts share a global rate limit.

Changing the password revokes existing sessions: the next HTTP request requires a new login, and open WebSockets close within one second. Do not set `webapp.public_url` to the onion address: Styx handles authentication.

Configuration, updates and tests: [guide (French)](docs/GUIDE.md) · [MIT license](LICENSE).
