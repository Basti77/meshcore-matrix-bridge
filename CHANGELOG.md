# Changelog

All notable changes are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.5.0] — 2026-07-06

### Added
- LPP telemetry support: `!mesh telemetry <name|keyprefix>` requests
  battery/temperature/… from a repeater, room server or companion;
  `!mesh autolog add|remove <name>` polls targets periodically in the
  background (`TELEMETRY_INTERVAL_S`, default 900 s); `!mesh chart
  <name> [hours]` renders the recorded series as a PNG and posts it as
  an image. Samples are persisted as JSONL (rotated at 10 MB).
- Unit tests for the pure logic (textsplit, command parsing, format
  helpers, drop log, state store, config) and a GitHub Actions CI that
  runs ruff + mypy + pytest on Python 3.10 and 3.12.

### Fixed
- The Matrix sync task is now watched: if it dies (expired token,
  persistent network failure) the bridge exits non-zero so systemd
  restarts it, instead of lingering with a dead sync loop.
- An unbalanced quote/apostrophe in a `!mesh` command (`!mesh dm Bob
  don't panic`) no longer kills the dispatch — the parser falls back to
  a plain whitespace split.
- `__version__` had drifted from the package version; it is now read
  from the package metadata.

### Changed
- matplotlib is an optional extra (`pip install '.[chart]'`) — only
  `!mesh chart` needs it.
- `bridge.env.example` uses neutral `example.org` placeholders; the
  env-file fallback path no longer hard-codes the author's home
  directory.
- README restructured (quick start, feature list brought up to date);
  the German quickstart moved to `README.de.md`.

### Removed
- `MESH_RELAY_CHANNELS` / `MESH_RELAY_CHANNEL_INDEXES`: both were
  parsed but never evaluated anywhere. Relaying is runtime state,
  toggled per channel via `!mesh relay <idx> on|off` and persisted in
  the state file.
- The `aiofiles` dependency (declared but never imported).

## [0.4.0] — 2026-04-21

### Added
- Dropped channel messages are now persisted to an append-only JSONL
  file at `~/.local/state/meshcore-matrix-bridge/rx-drops.jsonl`. On
  bridge restart the drop log is replayed to rebuild the `!mesh queue`
  counters and the per-channel 20-sample ringbuffer, so dropped
  messages survive service restarts and crashes. Rotation kicks in at
  2 MB (one generation kept, `.1` suffix), giving roughly 4 MB of
  history on disk. IO is zero when no channels drop.

### Changed
- `!mesh queue` counters now separate `seen` (in-memory, current
  process lifetime) from `dropped` (persistent since the log was
  first written).

## [0.3.0] — 2026-04-21

### Added
- `!mesh queue [idx]` — in-process RX bookkeeping. For every channel
  the bridge tracks how many messages have been seen and how many were
  silently dropped (relay off, no binding, or send failure), plus a
  20-sample ringbuffer of the last dropped messages for each channel.
  Without arguments you get a per-channel summary; with an index you
  get the dropped sample texts (including SNR / hops / timestamp).
  Makes it easy to spot channels that are active on the mesh but never
  make it into Matrix because the relay is off or the room was never
  bound/joined.

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
