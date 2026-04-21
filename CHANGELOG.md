# Changelog

All notable changes are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] — 2026-04-21

### Added
- Channel-slot management from Matrix:
  - `!mesh addchan <name> [idx]` writes a channel slot on the node. If
    `idx` is omitted the lowest free slot is picked. The 16-byte key is
    auto-derived from `sha256(name)[:16]` — the scope convention used by
    regional MeshCore communities (e.g. `de`, `de-nw-owl`, `europe`).
  - `!mesh delchan <idx>` clears a slot on the node and forgets the
    matching Matrix binding in one step.
- Hop count is now surfaced on every inbound message. Channel and DM
  formatting gained a `hops=N` field derived from the packet's
  `path_len`:
  - `hops=0` — direct / zero-hop reception
  - `hops=N` — reached via N intermediate repeaters
  - `hops=flood` — flood-routed, exact hop count unknown
    (`path_len == -1`)
  - `hops=?` — field not present in the payload (older firmware)

### Changed
- Inbound message format: `snr` is now rendered after `hops`, so
  messages read `hops=2 snr=12.25 ts=07:56:22 UTC`.

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
