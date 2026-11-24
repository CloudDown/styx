# Changelog

All notable changes to Styx are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-11-24

### Added

- Interactive host setup (`hermes styx setup`): offers Tor installation
  through the existing package manager, sets a missing passphrase, prepares
  the Webapp and starts the gate.
- macOS and native Windows hosts, with portable locks, protected Windows
  ACLs and identity-checked process operations; Linux keeps pidfd support.
- One-use native Hermes Webapp sign-in after Cerberus authentication, with
  session-bound entry passes, password-rotation checks and the official
  launch flow (Hermes sign-in providers stay enforced).
- Optional terminal interface (`hermes styx webapp tui`): a bundled xterm.js
  page whose WebSocket runs the fixed `hermes --tui` command in a POSIX PTY.
- Optional HTTP preload hints for the official renderer's main module and
  stylesheet; the document is never rewritten.
- Negotiated zstd compression for public immutable JS/CSS when the gate
  Python provides the standard `compression.zstd` module.
- Optional Tor v3 client authorization (`hermes styx client-auth`).

### Changed

- Cerberus login: viewport-selected WebP crops and a sub-1 KB inline preview
  replace the full painting embedded in the page; the form paints before the
  artwork. The requested internal page is preserved across login.
- Already encoded, API, authentication and cookie-bearing responses stay
  raw; only public immutable hashed assets may be re-compressed.
- Tor no longer inherits Hermes provider credentials from the environment.
- The Webapp is prepared through the public `hermes webapp --build-only`
  command; startup checks the served HTTP interface, not just the port.

### Removed

- The opt-in Fast Webapp (`hermes styx webapp fast`), its build pipeline and
  its pruned fork of the official renderer. The official Webapp is the
  default and remains untouched; the TUI stays available.
- The QR command.

### Fixed

- TUI PTY start failures now report a message and close the socket instead of
  raising `NameError`; a failed spawn no longer leaks the PTY master.
- The login form keeps deep links (`next`) through authentication and failed
  attempts, while still rejecting scheme-relative, backslash and oversized
  targets.
- Coverage: 169 unit tests, plugin validation and a pyflakes lint job.

