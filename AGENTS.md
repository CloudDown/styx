# Styx — AGENTS.md

Hermes plugin: expose the local Hermes **webapp** as a Tor v3 onion, behind a Cerberus password gate. Repo: `~/projet/styx`. Live install is a symlink `~/.hermes/plugins/styx` → this tree. Plugin id: `styx`. CLI: `hermes styx`.

User is French; replies short; verdict first. Do not print the onion URL in chat/slash commands.

## Architecture (do not invert)

```
Tor Browser → http://<v3>.onion
                 tor HS (port 80)
                    ↓
              127.0.0.1:9130   styx.gate  (Cerberus login + reverse proxy)
                    ↓  Host/Origin rewritten to loopback
              127.0.0.1:9120   hermes webapp
```

- Bind **loopback only**. Refuse non-loopback in `backend/gate.py`.
- Do **not** set `webapp.public_url` to the onion (Hermes DNS-rebinding + login gate). Styx owns auth.
- `hermes styx start` runs public `hermes webapp --build-only` (freshness/build owned by Hermes), enables `webapp.enabled` and `gateway ensure` / `restart --interrupt --detach` if 9120 is down (`backend/webapp_ensure.py`). Verify HTTP, not only TCP. `stop` kills tor+gate only — never the Hermes gateway (bots).
- Onion identity is `$HERMES_HOME/plugin-data/styx/hidden_service/`. **Never delete it on stop.** Same keys → same `.onion` after restart.
- `/styx` slash: up/down only, never the URL. URL = `hermes styx url` on the host.

## Files

| file | role |
|---|---|
| `plugin.yaml` | manifest, `config_schema` (autostart, target, gate_port) |
| `__init__.py` | `register()`: CLI + `/styx`; autostart thread with `may_restart_gateway=False` |
| `gate.py` | compatibility launcher for `python -m styx.gate`; keep the process command stable |
| `backend/cli.py` | `hermes styx {setup,status,start,stop,url,passwd,client-auth,doctor,webapp}` |
| `backend/bootstrap.py` | interactive host setup; confirmed package-manager installation of missing Tor |
| `backend/supervisor.py` | start/stop pids, state.json |
| `backend/webapp_ensure.py` | enable webapp + bring up gateway |
| `backend/gate.py` | Starlette 1.9 `lifespan=` (not `on_shutdown`); HTTP+WS proxy |
| `backend/webapp_handoff.py` | public CLI one-use native browser launch, only after Cerberus authentication |
| `backend/webapp_mode.py` | preference for the official Webapp or TUI |
| `backend/webapp_preload.py` | optional HTTP preload hints from the official renderer manifest, no HTML rewriting |
| `backend/offload.py` | bounded worker-thread offload; cancellation waits for the thread before freeing the slot |
| `backend/tui_webapp.py`, `assets/tui/` | opt-in terminal page; vendored xterm.js, no external assets |
| `backend/terminal.py` | POSIX PTY running the fixed `hermes --tui`; never a client-chosen command |
| `backend/headers.py` | strip styx_* cookies; force Host/Origin to `127.0.0.1:<port>` |
| `backend/asset_transfer.py` | negotiated streaming compression for public immutable hashed JS/CSS only; no shared cache |
| `backend/network.py` | shared loopback validation and port readiness helpers |
| `backend/storage.py` | atomic 0600 writes for passwords, state and process identities |
| `backend/platform_support.py` | portable locks/spawn flags; POSIX private modes and Windows protected ACLs |
| `backend/login_page.py` | minimal glass password field + same-origin immutable painting, **no external assets** |
| `backend/passwords.py` | scrypt; empty refused; **no min length** |
| `backend/sessions.py` | HMAC cookie `styx_session`, 12h; key derived from current password hash |
| `backend/tor_supervisor.py` | dedicated tor, `SocksPort 0`, HS v3 → gate |
| `backend/client_auth.py` | optional v3 x25519 client keys |
| `backend/paths.py` | all durable state under `plugin_data_dir("styx")`, never the install dir |
| `dashboard/` | tab `/styx` + `/api/plugins/styx/{status,start,stop}` |
| `desktop/plugin.js` | opt-in status chip (`defaultEnabled: false`) |

Implementation lives in `backend/`; package imports are relative (`from .passwords import` internally, `from .backend.cli import` at the root). Gate subprocess: `PYTHONPATH=<parent of plugin dir>` + `python -m styx.gate`. Folder name **must stay `styx`**. Keep `plugin.yaml`, `__init__.py`, `dashboard/` and `desktop/` at Hermes' expected locations. Install through `hermes plugins install CloudDown/styx`, update through `hermes plugins update styx`; the local development symlink is not a managed reinstall target.

## Commands

```bash
hermes styx passwd
hermes styx setup          # interactive: offer Tor install, set missing password, prepare webapp, start
hermes styx start          # enables webapp, (re)starts gateway if needed, then tor+gate
hermes styx url            # secret
hermes styx stop           # tor+gate only
hermes styx doctor
hermes styx webapp tui     # terminal-only interface: the TUI in a PTY (POSIX)
hermes plugins validate ~/projet/styx
hermes plugins doctor ~/projet/styx --ci
hermes --run-module unittest discover -s ~/projet/styx/tests -v
python3 -m unittest discover -s tests -v   # from ~/projet with PYTHONPATH=~/projet
# or: cd ~/projet && python3 -m unittest discover -s styx/tests -v
uvx ruff check
uvx ruff format --check
```

No pytest in the Hermes venv — use stdlib `unittest`. `ruff.toml` owns formatting and lint
rules (line length 100, py311 target); keep both checks green.

## Invariants

- Public plugin API only (`hermes_cli.config`, `plugins.plugin_storage`, …). `hermes plugins validate` must stay green.
- Do not monkeypatch Hermes core.
- Login page: no external network. Master painting in `assets/login-background.jpg`; prebuilt centered WebP crops in `assets/login/` selected natively by viewport via `<picture>`. Only those fixed, content-addressed public artwork URLs are immutable, never the form/CSRF. No request-time image processing. Minimal glass password field; mobile safe areas and keyboard-aware layout.
- Private webapp tabs need Hermes' native sessionStorage grant. After valid
  Cerberus auth, use public `hermes webapp --no-open --skip-build` and the
  official /webapp/launch → /webapp/window-session flow. Never read native
  secret files, patch the frontend or turn Hermes authentication off.
- Launch URLs must match the configured loopback upstream and become relative
  redirects. Never log their output/tickets. Honor explicitly configured extra
  Hermes sign-in providers; no private handoff for the dashboard target.
- The one-use _styx_entry navigation marker is bound to the Styx cookie and
  expires; every new tab/reload must be handled without a redirect loop.
- Do not rotate a valid login CSRF token on every GET; background favicon
  requests must not interfere with open login forms.
- Rate-limit login is **global** (Tor peers all look like 127.0.0.1).
- Pending login checks count toward the budget; scrypt stays off-loop and bounded.
- Password replacement revokes HTTP sessions on their next request and open
  WebSockets within one second. Do not cache the password hash at gate startup.
- Already encoded responses, APIs and auth pages stay raw: preserve
  Content-Encoding/Length and duplicate Set-Cookie headers. Only unencoded,
  public immutable hashed JS/CSS may use negotiated streaming compression (gzip, or zstd if both sides support it); respect
  ranges/no-transform, weaken ETags and remove original byte lengths/digests.
  Never cache private content or launch tickets. WebSocket handshake headers
  belong to the upstream client.
- Start/stop share a non-blocking native process lock. PID files carry process
  identity; legacy integers require command/profile checks. Linux keeps pidfds;
  macOS/Windows and older Linux use psutil guarded process operations. Never
  replace these checks with a bare PID signal or `os.kill(pid, 0)` on Windows.
- Platforms: linux/darwin/win32. Native Windows secrets need protected ACLs,
  not just chmod. Host CLI setup/start may offer Tor installation through an
  existing package manager, with explicit confirmation and normal admin/license
  prompts. Never install from gateway autostart, slash commands or dashboard/API;
  never bootstrap package managers or auto-accept agreement prompts.
- Tor logs use stdout redirected to tor.log. Do not quote filenames in a
  `Log notice file` directive: Tor treats those quotes as filename characters.
- Startup prepares the webapp through the public CLI, logs build errors to
  logs/webapp-build.log, and rejects missing/stale-interface HTTP responses.
- Native Windows/macOS CI is in .github/workflows/tests.yml. Do not claim those
  jobs passed unless they actually ran successfully.
- `client-auth` is opt-in (`--client-auth` after `hermes styx client-auth`).
- Session = OS user of Hermes (shell, files, keys). Treat like Web Access.

## Pitfalls

- Starlette 1.9: `lifespan=`, not `on_shutdown=`.
- websockets 15: `additional_headers=`, `max_size=None`.
- `dashboard/plugin_api.py` is imported **without a package** — it does `sys.path` + `import styx.backend.supervisor`.
- Autostart inside the gateway must **not** `gateway restart` (would kill itself).
- Do not disable `webapp.enabled` on stop.
- Do not log the onion at INFO in agent-facing surfaces.

## Not done / possible next

- Rotate onion (new HS keys) as an explicit CLI.
- Dashboard target auto-start (`hermes dashboard --no-open`) — webapp path is the one that auto-starts.
