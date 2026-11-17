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

- Bind **loopback only**. Refuse non-loopback in `gate.py`.
- Do **not** set `webapp.public_url` to the onion (Hermes DNS-rebinding + login gate). Styx owns auth.
- `hermes styx start` enables `webapp.enabled` and `gateway ensure` / `restart --interrupt --detach` if 9120 is down (`webapp_ensure.py`). `stop` kills tor+gate only — never the Hermes gateway (bots).
- Onion identity is `$HERMES_HOME/plugin-data/styx/hidden_service/`. **Never delete it on stop.** Same keys → same `.onion` after restart.
- `/styx` slash: up/down only, never the URL. URL = `hermes styx url` on the host.

## Files

| file | role |
|---|---|
| `plugin.yaml` | manifest, `config_schema` (autostart, target, gate_port) |
| `__init__.py` | `register()`: CLI + `/styx`; autostart thread with `may_restart_gateway=False` |
| `cli.py` | `hermes styx {status,start,stop,url,passwd,client-auth,doctor,qr}` |
| `supervisor.py` | start/stop pids, state.json |
| `webapp_ensure.py` | enable webapp + bring up gateway |
| `gate.py` | Starlette 1.9 `lifespan=` (not `on_shutdown`); HTTP+WS proxy |
| `headers.py` | strip styx_* cookies; force Host/Origin to `127.0.0.1:<port>` |
| `network.py` | shared loopback validation and port readiness helpers |
| `storage.py` | atomic 0600 writes for passwords, state and process identities |
| `login_page.py` | minimal glass password field + local painting embedded as data URI, **no external assets** |
| `passwords.py` | scrypt; empty refused; **no min length** |
| `sessions.py` | HMAC cookie `styx_session`, 12h; key derived from current password hash |
| `tor_supervisor.py` | dedicated tor, `SocksPort 0`, HS v3 → gate |
| `client_auth.py` | optional v3 x25519 client keys |
| `paths.py` | all durable state under `plugin_data_dir("styx")`, never the install dir |
| `dashboard/` | tab `/styx` + `/api/plugins/styx/{status,start,stop}` |
| `desktop/plugin.js` | opt-in status chip (`defaultEnabled: false`) |

Package imports are relative (`from .passwords import`). Gate subprocess: `PYTHONPATH=<parent of plugin dir>` + `python -m styx.gate`. Folder name **must stay `styx`**.

## Commands

```bash
hermes styx passwd
hermes styx start          # enables webapp, (re)starts gateway if needed, then tor+gate
hermes styx url            # secret
hermes styx stop           # tor+gate only
hermes styx doctor
hermes plugins validate ~/projet/styx
hermes --run-module unittest discover -s ~/projet/styx/tests -v
python3 -m unittest discover -s tests -v   # from ~/projet with PYTHONPATH=~/projet
# or: cd ~/projet && python3 -m unittest discover -s styx/tests -v
```

No pytest in the Hermes venv — use stdlib `unittest`.

## Invariants

- Public plugin API only (`hermes_cli.config`, `plugins.plugin_storage`, …). `hermes plugins validate` must stay green.
- Do not monkeypatch Hermes core.
- Login page: zero network. Local painting in `assets/login-background.jpg`, minimal glass password field.
- Rate-limit login is **global** (Tor peers all look like 127.0.0.1).
- Pending login checks count toward the budget; scrypt stays off-loop and bounded.
- Password replacement revokes HTTP sessions on their next request and open
  WebSockets within one second. Do not cache the password hash at gate startup.
- Proxy responses stay raw: preserve Content-Encoding/Length and duplicate
  Set-Cookie headers. WebSocket handshake headers belong to the upstream client.
- Start/stop share a non-blocking process lock. PID files carry process identity;
  legacy integers require command/profile checks. Signals use Linux pidfds.
- `client-auth` is opt-in (`--client-auth` after `hermes styx client-auth`).
- Session = OS user of Hermes (shell, files, keys). Treat like Web Access.

## Pitfalls

- Starlette 1.9: `lifespan=`, not `on_shutdown=`.
- websockets 15: `additional_headers=`, `max_size=None`.
- `dashboard/plugin_api.py` is imported **without a package** — it does `sys.path` + `import styx.supervisor`.
- Autostart inside the gateway must **not** `gateway restart` (would kill itself).
- Do not disable `webapp.enabled` on stop.
- Do not log the onion at INFO in agent-facing surfaces.

## Not done / possible next

- Rotate onion (new HS keys) as an explicit CLI.
- Dashboard target auto-start (`hermes dashboard --no-open`) — webapp path is the one that auto-starts.
- ASCII QR needs optional `qrcode`; not a dependency.
