# MeshCore Companion UART — notes

This file captures what I learned about the Companion firmware's serial
protocol while writing the bridge, so future maintainers don't have to
re-read the library source code.

## Framing

- TX (host → node): `0x3C | size_le16 | payload`
- RX (node → host): `0x3E | size_le16 | payload`
- Baudrate 115200, 8N1. `RTS` must be `False` on open (otherwise ESP32 boards
  reset when the port is opened).
- Many radios print boot/debug messages on the same UART. The library
  tolerates this by scanning for `0x3E` and discarding leading junk.

## Event dispatch

`meshcore.MeshCore` starts an asyncio dispatcher that reads frames, decodes
them into typed events (`meshcore.EventType`), and pushes them into an
`asyncio.Queue`. Consumers:

- **Callbacks**: `mc.subscribe(EventType.X, async_cb)`.
- **One-shot**: `await mc.wait_for_event(EventType.X, timeout=...)`.

There is **no** async iterator — the library intentionally uses a fan-out
pattern so multiple parts of an app can observe the same event.

## Pending messages queue (important!)

The node does **not** push incoming radio messages spontaneously. Instead:

1. Node emits `EventType.MESSAGES_WAITING` (a short push notification).
2. Host replies with `get_msg` (opcode `0x0A`) repeatedly.
3. For each call it gets back either `CONTACT_MSG_RECV`, `CHANNEL_MSG_RECV`,
   `NO_MORE_MSGS`, or `ERROR`.

The library can automate this with `start_auto_message_fetching()`. The
bridge uses this by default so channel messages are picked up immediately.

Calling `get_msg` manually (which is what `!mesh fetch` / `!mesh public` do)
drains the same queue. You cannot fetch older messages than what the node
still has queued — the Companion firmware does **not** keep persistent
history.

## Channels

- Enumerated by index (`0..N`) via `get_channel(idx)`; walk until you get
  `EventType.ERROR`.
- `#public` is conventionally index 0 with name `"public"`.
- Channel secrets for `#<name>` channels are deterministically
  `sha256(name)[0:16]` — the firmware computes this itself when you set a
  channel name starting with `#`.
- **Channel messages are fire-and-forget** — there is no ACK, and `send_msg`
  returns immediately after the node confirms the queue insertion.

## DMs and ACKs

- `send_msg` returns a `MSG_SENT` payload containing:
  - `expected_ack` (bytes) — match against the `code` field of a future
    `ACK` event to confirm delivery.
  - `suggested_timeout` (ms) — how long to wait before retransmitting.
- `send_msg_with_retry` wraps the ACK wait and fallback to flood.
- For contacts with `out_path_len == -1` (no known route) only flood works;
  there is no way to ACK those reliably without doing a `send_path_discovery_sync`
  first.
