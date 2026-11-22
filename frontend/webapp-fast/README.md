# Hermes Fast — pruned official renderer

Fast compiles a private copy of the official Webapp renderer at the Hermes revision pinned in
`build.mjs`. It runs React in the browser and uses the official session actions, chat thread,
composer, model menus, attachments, and voice hooks. `prune.mjs` removes composition and
bindings in the copy only. Keep the allowlist in [FAST.md](../../docs/FAST.md) as the scope
for rebasing. The official renderer is never patched or replaced.

The host needs the pinned Hermes **source** checkout and its prepared Webapp dependencies
(`hermes webapp --build-only`), plus Node.js 26 or newer and Git. `hermes styx webapp fast`
builds on first use and reuses the result thereafter. Use `--source /path/to/hermes-agent`
to build from a checkout outside the default location. Build
artifacts are stored in Styx plugin data, not distributed in the repository. The original
Hermes renderer is MIT-licensed; its license is copied into each build.
