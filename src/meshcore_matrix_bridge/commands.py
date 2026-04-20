"""Command parser for !mesh <subcommand> invocations from Matrix control room."""
from __future__ import annotations

import html as html_mod
import logging
import shlex
from dataclasses import dataclass
from typing import Any

from .meshnode import MeshNode


log = logging.getLogger(__name__)


HELP = """\
MeshCore bridge commands (prefix: {prefix})

General
  {prefix} help                    — this help
  {prefix} status                  — node info + battery
  {prefix} ping                    — bridge roundtrip

MeshCore state
  {prefix} contacts                — list known contacts
  {prefix} channels                — list channels + their Matrix rooms

Direct messaging
  {prefix} dm <name|keyprefix> <text…>
                                    — send a DM (retries + flood fallback)

Channels / rooms
  {prefix} bind <idx> [alias]      — create (or reuse) a Matrix room for
                                     channel <idx>. Room is world-readable,
                                     public-join, write-locked to allowed
                                     users. Optional alias local-part, e.g.
                                     mesh-public.
  {prefix} unbind <idx>            — forget the Matrix room mapping for <idx>
                                     (does NOT delete the room).
  {prefix} relay <idx> on|off      — toggle auto-forwarding of channel RX
                                     into the bound Matrix room.
  {prefix} fetch [idx]             — drain the node's pending-message queue.
                                     Without <idx>, drops everything into the
                                     bound rooms (DMs stay in control room).
                                     With <idx>, only that channel is kept.
  {prefix} public [limit]          — shortcut: fetch, filter to #public,
                                     drop into the bound #public room.
  {prefix} send <idx> <text…>      — send into a channel from the control
                                     room (alternative to typing in the
                                     room directly).
"""


@dataclass
class CommandResult:
    plain: str
    html: str | None = None
    # optional side-effect: ask the caller to re-route output elsewhere
    target_room: str | None = None


def _escape(s: str) -> str:
    return html_mod.escape(s, quote=False)


def _fmt_contact(c: dict[str, Any]) -> tuple[str, str]:
    name = c.get("adv_name") or "(unnamed)"
    pk = (c.get("public_key") or "")[:12]
    path = c.get("out_path_len", "?")
    plain = f"  {name:<22} {pk}  pathlen={path}"
    html = f"<li><b>{_escape(name)}</b> <code>{pk}</code> pathlen={path}</li>"
    return plain, html


def fmt_msg(kind: str, payload: dict[str, Any], node: MeshNode) -> tuple[str, str]:
    text = payload.get("text", "")
    ts = payload.get("sender_timestamp")
    snr = payload.get("SNR")
    ts_str = f"ts={ts} UTC" if ts is not None else "ts=?"
    if kind == "dm":
        pk = payload.get("pubkey_prefix", "")[:12]
        contact = None
        if node.mc is not None:
            contact = node.mc.get_contact_by_key_prefix(pk)
        sender = (contact or {}).get("adv_name") or pk
        plain = f"[DM {sender}] {text}  (snr={snr}, {ts_str})"
        html = (
            f"📩 <b>DM</b> from <b>{_escape(sender)}</b> <code>{pk}</code><br/>"
            f"{_escape(text)}<br/><small>snr={snr} {ts_str}</small>"
        )
        return plain, html
    # channel
    idx = payload.get("channel_idx")
    pk = (payload.get("pubkey_prefix") or "")[:12]
    prefix_html = ""
    prefix_plain = ""
    if pk:
        contact = None
        if node.mc is not None:
            contact = node.mc.get_contact_by_key_prefix(pk)
        sender = (contact or {}).get("adv_name") or pk
        prefix_plain = f"<{sender}> "
        prefix_html = f"<b>&lt;{_escape(sender)}&gt;</b> "
    plain = f"[CH#{idx}] {prefix_plain}{text}  (snr={snr}, {ts_str})"
    html = f"📡 <b>#{idx}</b> {prefix_html}{_escape(text)}<br/><small>snr={snr} {ts_str}</small>"
    return plain, html


class CommandHandler:
    """Routes !mesh subcommands. Needs a ``bridge`` instance so some commands
    can touch the channel/room bindings."""

    def __init__(self, node: MeshNode, bridge: Any, prefix: str = "!mesh") -> None:
        self.node = node
        self.bridge = bridge
        self.prefix = prefix

    def matches(self, body: str) -> bool:
        # use first non-empty line only (Element sends Shift+Enter as \n)
        first = next((ln for ln in body.splitlines() if ln.strip()), "").strip()
        return first == self.prefix or first.startswith(self.prefix + " ")

    async def dispatch(self, body: str, source_room: str | None = None) -> CommandResult:
        # take first non-empty line only
        first_line = next((ln for ln in body.splitlines() if ln.strip()), "").strip()
        parts = shlex.split(first_line)
        if not parts or parts[0] != self.prefix:
            return CommandResult("(not a mesh command)")
        args = parts[1:]
        if not args or args[0] in ("help", "?", "-h", "--help"):
            return CommandResult(HELP.format(prefix=self.prefix))

        cmd = args[0]
        rest = args[1:]
        try:
            if cmd == "ping":
                return CommandResult("pong")

            if cmd == "status":
                info = await self.node.self_info()
                lines = ["node status:"]
                for k, v in info.items():
                    lines.append(f"  {k}: {v}")
                return CommandResult("\n".join(lines) if info else "node status: (no info)")

            if cmd == "contacts":
                contacts = await self.node.list_contacts()
                if not contacts:
                    return CommandResult("no contacts yet")
                plain_lines = [f"{len(contacts)} contact(s):"]
                html_items = []
                for c in contacts:
                    p, h = _fmt_contact(c)
                    plain_lines.append(p)
                    html_items.append(h)
                return CommandResult(
                    "\n".join(plain_lines),
                    f"<b>{len(contacts)} contact(s)</b><ul>{''.join(html_items)}</ul>",
                )

            if cmd == "channels":
                chans = await self.node.list_channels()
                if not chans:
                    return CommandResult("no channels configured")
                bindings = self.bridge.get_channel_bindings()
                plain_lines = [f"{len(chans)} channel(s):"]
                html_items = []
                for ch in chans:
                    idx = ch.get("channel_idx")
                    name = ch.get("channel_name") or "(unnamed)"
                    b = bindings.get(str(idx), {})
                    room = b.get("room_id") or "(unbound)"
                    relay = "on" if b.get("relay", False) else "off"
                    plain_lines.append(f"  #{idx:<2} {name:<20} room={room} relay={relay}")
                    html_items.append(
                        f"<li><b>#{idx}</b> {_escape(name)} "
                        f"room=<code>{_escape(room)}</code> relay={relay}</li>"
                    )
                return CommandResult(
                    "\n".join(plain_lines),
                    f"<b>{len(chans)} channel(s)</b><ul>{''.join(html_items)}</ul>",
                )

            if cmd == "bind":
                if not rest or not rest[0].lstrip("-").isdigit():
                    return CommandResult("usage: !mesh bind <idx> [alias]")
                idx = int(rest[0])
                alias = rest[1] if len(rest) > 1 else None
                room_id, alias_full, created = await self.bridge.bind_channel(idx, alias)
                state = "created" if created else "already bound"
                return CommandResult(
                    f"✓ channel #{idx} {state}: room={room_id}"
                    + (f" alias={alias_full}" if alias_full else "")
                )

            if cmd == "unbind":
                if not rest or not rest[0].lstrip("-").isdigit():
                    return CommandResult("usage: !mesh unbind <idx>")
                idx = int(rest[0])
                ok = self.bridge.unbind_channel(idx)
                return CommandResult(
                    f"✓ forgot binding for #{idx}" if ok else f"no binding for #{idx}"
                )

            if cmd == "relay":
                if len(rest) < 2 or not rest[0].lstrip("-").isdigit() or rest[1] not in ("on", "off"):
                    return CommandResult("usage: !mesh relay <idx> on|off")
                idx = int(rest[0])
                on = rest[1] == "on"
                ok = self.bridge.set_channel_relay(idx, on)
                return CommandResult(
                    f"✓ relay for #{idx} = {'on' if on else 'off'}"
                    if ok else f"no binding for #{idx} (bind first)"
                )

            if cmd == "fetch":
                only_idx: int | None = None
                if rest and rest[0].lstrip("-").isdigit():
                    only_idx = int(rest[0])
                count = await self.bridge.drain_backlog(only_channel=only_idx)
                return CommandResult(
                    f"drained {count} pending message(s)"
                    + (f" (filtered to #{only_idx})" if only_idx is not None else "")
                )

            if cmd == "public":
                limit = 200
                if rest and rest[0].isdigit():
                    limit = int(rest[0])
                count = await self.bridge.drain_backlog(only_public=True, limit=limit)
                return CommandResult(f"drained {count} #public message(s)")

            if cmd == "dm":
                if len(rest) < 2:
                    return CommandResult("usage: !mesh dm <name|keyprefix> <text…>")
                target = rest[0]
                text = " ".join(rest[1:])
                r = await self.bridge.send_dm(target, text)
                if r["ok"]:
                    return CommandResult(f"✓ DM to {target} delivered")
                return CommandResult(f"✗ DM to {target} failed: {r.get('error')}")

            if cmd == "send":
                if len(rest) < 2 or not rest[0].lstrip("-").isdigit():
                    return CommandResult("usage: !mesh send <channel_idx> <text…>")
                idx = int(rest[0])
                text = " ".join(rest[1:])
                r = await self.bridge.send_channel_split(idx, text)
                if r["ok"]:
                    return CommandResult(f"✓ sent {r['parts']} part(s) to #{idx}")
                return CommandResult(f"✗ send to #{idx} failed: {r.get('error')}")

            return CommandResult(f"unknown subcommand: {cmd}\n\n" + HELP.format(prefix=self.prefix))
        except Exception as exc:  # pragma: no cover
            log.exception("Command %s failed", cmd)
            return CommandResult(f"internal error: {exc!r}")
