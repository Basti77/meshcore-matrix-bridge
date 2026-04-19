# Changelog

All notable changes are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] — 2026-04-19

Initial public release.

### Added
- Async MeshCore wrapper (`MeshNode`) on top of `meshcore>=2.3`. Supports
  **both USB serial and BLE** transport — most RAK4631 Companion builds are
  BLE-only, so BLE is a first-class citizen.
- Matrix client (`MatrixBot`) based on `matrix-nio`, unencrypted, with
  allow-list, auto-accept for invites from allow-listed users, and
  auto-creation of a DM control room on first start.
### Added
- `!mesh` command handler: `help`, `status`, `ping`, `contacts`, `channels`,
  `bind <idx> [alias]`, `unbind <idx>`, `relay <idx> on|off`,
  `fetch [idx]`, `public [limit]`, `dm <target> <text>`,
  `send <idx> <text>`.
- **Channels as public Matrix rooms** (amateur-radio style): world-readable,
  public-join, `events_default = 50` so only the bot + allow-listed users
  can transmit while everyone else reads along.
- Automatic text splitting at ~140 chars with `(i/n)` part prefixes for
  outgoing radio payloads.
- Standalone CLI (`mc-cli`) for local terminal send/receive without Matrix.
- Systemd user service unit.
- `.env.example` and full README.
