# Styx

Access your Hermes web UI through Tor Browser.
One onion address, one password. No ports exposed to your local network.

![Styx login page: a password field over a mythological painting, with Cerberus by the river Styx.](docs/login.png)

## 1. Install

On the machine running **Hermes ≥ 0.22.0**, open a terminal:

```bash
hermes plugins install CloudDown/styx
hermes styx setup
```

Hermes prompts for dependency installation and plugin activation. Approve these to continue. If you leave the plugin disabled, run `hermes plugins enable styx` before setup.

Setup asks for a password, prepares the webapp and starts Styx. Choose a long, unique passphrase; existing passwords are never overwritten. If Tor is missing, setup offers to install it through your existing package manager, with your confirmation.

Linux, macOS and native Windows are supported. Windows requires a filesystem with private ACLs, normally NTFS. Platform prerequisites and manual Tor setup are covered in the [guide (French)](docs/GUIDE.md#linux-macos-et-windows). Autostart and dashboard/API calls never install system packages.

## 2. Open the passage

```bash
hermes styx url
```

Styx asks Hermes to prepare the webapp (reusing a fresh bundle or building a missing/outdated one), enables it, and starts or restarts the gateway if needed. It checks the actual HTTP response, not merely an open port. Copy the displayed address **into Tor Browser**, then enter your password. Keep the host machine awake; Tor can add latency.

After Cerberus, Styx uses Hermes' official one-use launch flow to sign the tab in automatically. You do not need to run `hermes webapp` manually. New tabs and reloads are handled too, without disabling Hermes authentication or modifying its code. An additional Hermes sign-in provider, if explicitly configured, is still respected.

![Hermes webapp open in Tor Browser, with the onion address and session list redacted.](docs/tor-webapp.png)

Hermes in Tor Browser. The onion address and session list are redacted for privacy.

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
| Start again after stopping | `hermes styx start` |
| Check status on the host | `hermes styx status` |
| Diagnose a problem | `hermes styx doctor` |
| Change your password | `hermes styx passwd` |
| Install missing prerequisites and start | `hermes styx setup` |
| Use the optional lightweight chat interface | `hermes styx webapp fast` |
| Return to the full official interface | `hermes styx webapp hermes` |
| Check from chat without revealing the address | `/styx` |

The dashboard's **Styx** tab also lets you start, stop and copy the address. The Desktop status chip is opt-in, under **Capabilities → Plugins**.

**Styx Fast** shows streaming Markdown replies, recent history and a searchable model menu grouped by provider. The composer supports files, reasoning effort and, when the browser allows microphone access, dictation and voice turns through Hermes. Double-click a session title to rename it (or use the pencil on mobile); the trash button asks before deleting. Settings can follow Hermes’ appearance or use the default Nous light or dark theme. Fast uses the same native Hermes browser authorization and requires a gateway offering `hermes-gateway-v1` and GUI sessions. Advanced tools remain in full Hermes, reachable from Fast's settings. The official Webapp stays the default; use `hermes styx webapp status` to see the saved choice.

To require a per-device Tor key in addition to the password, see the [guide (French)](docs/GUIDE.md#clé-tor-par-appareil).

## Access and privacy

A session grants the permissions of the OS user running Hermes, **including shell access, files and keys**. Only share access with someone you would trust with that account.

Hermes and Cerberus listen only on loopback. Tor publishes the entry point; no port is exposed to the LAN. The login page loads no external resources. Login attempts share a global rate limit.

Changing the password revokes existing sessions: the next HTTP request requires a new login, and open WebSockets close within one second. Do not set `webapp.public_url` to the onion address: Styx handles authentication.

### What the plugin runs and stores

- **Network:** a dedicated Tor process connects to the Tor network and publishes the password gate as an onion service. The gate proxies HTTP and WebSockets only to the configured loopback Hermes interface. Styx has no telemetry, analytics or usage reporting. Hermes and any integrations used through its UI retain their own network behaviour.
- **Background processes:** `setup` / `start` launches Tor and the Cerberus gate as the current OS user. Tor receives only allowlisted OS path, home and temporary-directory variables, not Hermes provider API keys. The processes keep running until `hermes styx stop` or process/host shutdown. Optional autostart is off by default; stopping Styx never stops the Hermes gateway.
- **Host commands and configuration:** Styx uses public Hermes config/storage APIs and CLI commands. Starting the default webapp target enables `webapp.enabled`, prepares the interface with `hermes webapp --build-only`, and may start or restart the gateway if its HTTP interface is unavailable. After a valid Cerberus login, it obtains a one-use native browser launch through `hermes webapp --no-open --skip-build`; additional Hermes sign-in providers remain enforced. A gateway restart can interrupt active work.
- **Optional system installation:** in an interactive host terminal only, setup can offer to install Tor through the existing system package manager. It shows the command and requires explicit confirmation; sudo/doas, administrator and license prompts remain with the package manager. Package downloads use that manager's configured repositories and verification. Styx does not bundle a Tor binary, bootstrap a package manager or download an installer script.
- **Local files and secrets:** durable state lives under the active profile's `$HERMES_HOME/plugin-data/styx/`: a salted scrypt password hash, session-signing key, Tor onion identity, optional client authorizations, PID/state files and logs. These are protected by POSIX permissions or Windows ACLs; backups must be protected too. Styx reads its own process information and standard OS/package-manager locations outside that directory to identify processes and find Tor. It does not read Hermes authentication files, `.env` files, browser profiles or other applications' credential stores.
- **Optional Fast client:** runs as a separate browser page behind Cerberus, not in the Desktop renderer. It uses the native Hermes tab authorization and sends chat, files and microphone recordings (only on request and with browser permission) to the same Hermes instance, whose configured services still apply. The client does not load a CDN. It bundles the upstream [Marked 18.1.0](https://github.com/markedjs/marked/tree/v18.1.0) JavaScript and its [MIT license](assets/fast/vendor/marked.LICENSE) for local Markdown tokenization; it renders tokens as DOM nodes rather than injecting generated HTML.
- **Updates:** Styx has no self-updater. Use `hermes plugins update styx`; catalog installations follow the reviewed commit pin.

The automated backend suite runs on Linux, macOS and Windows with Python 3.13 and 3.14. Raspberry Pi / ARM deployment has not been tested; use a working, supported Hermes installation and system Tor. These tests are not an independent security audit.

## Artwork

The login page, screenshot and catalog card reuse the same public-domain Luca Giordano fresco. [Artwork source and reproduction details](docs/ARTWORK.md).

Configuration, updates and tests: [guide (French)](docs/GUIDE.md) · [MIT license](LICENSE).
