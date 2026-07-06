"""Command parser for !mesh <subcommand> invocations from Matrix control room."""
from __future__ import annotations

from datetime import datetime, timezone

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
  {prefix} telemetry <name|keyprefix>
                                    — request LPP telemetry (battery/temp/…)
                                      from a repeater/companion/room-server
  {prefix} autolog                 — list targets polled periodically
  {prefix} autolog add <name>      — start periodic polling of <name>
  {prefix} autolog remove <name>   — stop periodic polling
  {prefix} chart <name> [hours]    — render a PNG chart of the recorded
                                      telemetry (default: 24 h, max 720)

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
  {prefix} addchan <name> [idx]    — write a channel slot on the node
                                     (key auto-derived from sha256(name)).
                                     Picks the lowest free slot if <idx>
                                     is omitted.
  {prefix} delchan <idx>           — clear slot <idx> on the node and
                                     forget its Matrix binding.
  {prefix} queue [idx]             — show in-process RX bookkeeping
                                     (messages seen vs. silently dropped
                                     because relay was off / no binding /
                                     send failed). Optional <idx> shows
                                     the last ~20 dropped samples for
                                     one channel including text + SNR.
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


def _fmt_ts(ts: Any) -> str:
    """Format a meshcore sender_timestamp (unix epoch, UTC) as ISO datetime.

    Meshcore radio packets carry the sender's clock as a raw UTC epoch int —
    that's the radio standard, keep it that way upstream, but render it
    readable for humans in the Matrix bridge output.
    """
    if ts is None:
        return "ts=?"
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return f"ts={ts}"
    return f"ts={dt.strftime('%H:%M:%S')} UTC"


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
    path_len = payload.get("path_len")
    ts_str = _fmt_ts(ts)
    hops_str = _fmt_hops(path_len)
    if kind == "dm":
        pk = payload.get("pubkey_prefix", "")[:12]
        contact = None
        if node.mc is not None:
            contact = node.mc.get_contact_by_key_prefix(pk)
        sender = (contact or {}).get("adv_name") or pk
        plain = f"[DM {sender}] {text}  ({hops_str}, snr={snr}, {ts_str})"
        html = (
            f"📩 <b>DM</b> from <b>{_escape(sender)}</b> <code>{pk}</code><br/>"
            f"{_escape(text)}<br/><small>{hops_str} snr={snr} {ts_str}</small>"
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
    plain = f"[CH#{idx}] {prefix_plain}{text}  ({hops_str}, snr={snr}, {ts_str})"
    html = f"📡 <b>#{idx}</b> {prefix_html}{_escape(text)}<br/><small>{hops_str} snr={snr} {ts_str}</small>"
    return plain, html


def _fmt_hops(path_len: Any) -> str:
    """Format the path_len field from a received mesh packet.

    meshcore-lib conventions:
      * ``path_len == 0``  → direct / zero-hop reception
      * ``path_len == -1`` → flood-routed, concrete hop count unknown
      * ``path_len >= 1``  → number of intermediate repeaters
    """
    if path_len is None:
        return "hops=?"
    try:
        n = int(path_len)
    except (TypeError, ValueError):
        return f"hops={path_len}"
    if n < 0:
        return "hops=flood"
    return f"hops={n}"


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

            if cmd == "addchan":
                if not rest:
                    return CommandResult("usage: !mesh addchan <name> [idx]")
                name = rest[0]
                if len(rest) > 1 and rest[1].lstrip("-").isdigit():
                    idx = int(rest[1])
                else:
                    free = await self.node.find_free_channel_slot()
                    if free is None:
                        return CommandResult("no free channel slot on the node")
                    idx = free
                res = await self.node.set_channel(idx, name)
                if not res.get("ok"):
                    return CommandResult(f"✗ set_channel failed: {res.get('error')}")
                return CommandResult(
                    f"✓ channel slot #{idx} = {name!r} "
                    f"(key auto-derived; use `!mesh bind {idx}` to map to a Matrix room)"
                )

            if cmd == "delchan":
                if not rest or not rest[0].lstrip("-").isdigit():
                    return CommandResult("usage: !mesh delchan <idx>")
                idx = int(rest[0])
                res = await self.node.set_channel(idx, "", b"\x00" * 16)
                if not res.get("ok"):
                    return CommandResult(f"✗ clear slot #{idx} failed: {res.get('error')}")
                unbound = self.bridge.unbind_channel(idx)
                suffix = " (Matrix binding also forgotten)" if unbound else ""
                return CommandResult(f"✓ cleared node slot #{idx}{suffix}")

            if cmd == "queue":
                snap = self.bridge.rx_snapshot()
                chans = snap["channels"]
                dm = snap["dm"]
                dm_samples = snap["dm_samples"]

                # detail view for a specific channel
                if rest and rest[0].lstrip("-").isdigit():
                    idx = int(rest[0])
                    info = chans.get(idx)
                    if not info:
                        return CommandResult(
                            f"no RX stats for #{idx} yet "
                            "(nothing received on that channel since the bridge started)"
                        )
                    samples = info.get("samples") or []
                    plain_lines = [
                        f"RX stats #{idx} ({info.get('name') or '?'}):",
                        f"  seen={info['seen']}  dropped={info['dropped']}  "
                        f"relay={'on' if info['relay'] else 'off'}  "
                        f"room={info.get('room_id') or '(unbound)'}",
                        f"  last {len(samples)} dropped sample(s):",
                    ]
                    html_lines = [
                        f"<b>RX stats #{idx}</b> ({_escape(info.get('name') or '?')})<br/>",
                        f"seen=<b>{info['seen']}</b> dropped=<b>{info['dropped']}</b> ",
                        f"relay={'on' if info['relay'] else 'off'} ",
                        f"room=<code>{_escape(info.get('room_id') or '(unbound)')}</code>",
                        f"<br/>last {len(samples)} dropped sample(s):<ul>",
                    ]
                    for s in samples:
                        ts = _fmt_ts(s.get("sender_ts") or s.get("ts"))
                        hops = _fmt_hops(s.get("path_len"))
                        snr = s.get("snr")
                        text = s.get("text") or ""
                        reason = s.get("reason", "?")
                        plain_lines.append(
                            f"    [{reason}] {text}  ({hops}, snr={snr}, {ts})"
                        )
                        html_lines.append(
                            f"<li>[{_escape(reason)}] {_escape(text)} "
                            f"<small>{hops} snr={snr} {ts}</small></li>"
                        )
                    if not samples:
                        plain_lines.append("    (none)")
                        html_lines.append("<li><i>(none)</i></li>")
                    html_lines.append("</ul>")
                    return CommandResult("\n".join(plain_lines), "".join(html_lines))

                # summary view
                if not chans and dm["seen"] == 0:
                    return CommandResult(
                        "RX bookkeeping is empty — nothing received on any channel "
                        "since the bridge started."
                    )
                plain_lines = ["RX bookkeeping (since bridge start):"]
                html_items = []
                for idx in sorted(chans):
                    info = chans[idx]
                    flag = "⚠ " if info["dropped"] else "   "
                    plain_lines.append(
                        f"  {flag}#{idx:<2} {info.get('name') or '?':<16} "
                        f"seen={info['seen']:<4} dropped={info['dropped']:<4} "
                        f"relay={'on' if info['relay'] else 'off'}"
                    )
                    html_items.append(
                        f"<li>{flag}<b>#{idx}</b> {_escape(info.get('name') or '?')} "
                        f"seen=<b>{info['seen']}</b> dropped=<b>{info['dropped']}</b> "
                        f"relay={'on' if info['relay'] else 'off'}</li>"
                    )
                plain_lines.append(
                    f"  DM seen={dm['seen']} dropped={dm['dropped']}"
                )
                html_items.append(
                    f"<li>DM seen=<b>{dm['seen']}</b> dropped=<b>{dm['dropped']}</b></li>"
                )
                if any(c["dropped"] for c in chans.values()) or dm["dropped"]:
                    plain_lines.append(
                        "  → use `!mesh queue <idx>` to see dropped samples for a channel."
                    )
                return CommandResult(
                    "\n".join(plain_lines),
                    f"<b>RX bookkeeping (since bridge start)</b><ul>{''.join(html_items)}</ul>",
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

            if cmd == "telemetry":
                if not rest:
                    return CommandResult("usage: !mesh telemetry <name|keyprefix>")
                target = rest[0]
                r = await self.node.telemetry(target)
                if not r["ok"]:
                    return CommandResult(f"✗ telemetry {target} failed: {r.get('error')}")
                sensors = r.get("sensors") or []
                # group LPP values by channel/type → compact lines
                # LPP types we care to label nicely (others fall back to raw type name)
                LABEL = {
                    "voltage": ("🔋", "V"),
                    "battery": ("🔋", "V"),
                    "temperature": ("🌡", "°C"),
                    "humidity": ("💧", "%"),
                    "pressure": ("📉", "hPa"),
                    "luminosity": ("☀️", "lx"),
                    "gps": ("📍", ""),
                }
                lines: list[str] = []
                for s in sensors:
                    if not isinstance(s, dict):
                        continue
                    typ = str(s.get("type") or "").lower()
                    val = s.get("value")
                    ch = s.get("channel")
                    ico, unit = LABEL.get(typ, ("·", ""))
                    if typ == "voltage" and isinstance(val, (int, float)):
                        pretty = f"{val:.2f} {unit}"
                    elif typ == "temperature" and isinstance(val, (int, float)):
                        pretty = f"{val:.1f} {unit}"
                    elif isinstance(val, float):
                        pretty = f"{val:.2f} {unit}".rstrip()
                    else:
                        pretty = f"{val} {unit}".rstrip()
                    label = s.get("type") or "?"
                    ch_str = f" (ch{ch})" if ch not in (None, 1) else ""
                    lines.append(f"{ico} {label}: {pretty}{ch_str}")
                if not lines:
                    lines.append("(no sensor values in response)")
                pl_raw = r.get("path_len")
                hops_str = _fmt_hops(pl_raw) if pl_raw is not None else ""
                header = f"📡 telemetry {target}" + (f"  [{hops_str}]" if hops_str else "")
                body = header + "\n" + "\n".join(lines)
                return CommandResult(body)

            if cmd == "autolog":
                watches = self.bridge.get_telem_watches()
                if not rest:
                    if not watches:
                        return CommandResult("autolog: (empty) — add with `!mesh autolog add <name>`")
                    return CommandResult("autolog targets:\n" + "\n".join(f"  • {t}" for t in watches))
                sub = rest[0].lower()
                if sub in ("add", "a", "+") and len(rest) >= 2:
                    target = " ".join(rest[1:])
                    if target in watches:
                        return CommandResult(f"autolog: {target} already watched")
                    watches.append(target)
                    self.bridge.set_telem_watches(watches)
                    # kick off an immediate poll so the user gets a first data point
                    import asyncio as _asyncio
                    _asyncio.create_task(self.bridge.poll_telemetry_once(target))
                    return CommandResult(
                        f"✓ autolog added: {target} "
                        f"(first poll running, regular interval applies afterwards)"
                    )
                if sub in ("remove", "rm", "del", "-") and len(rest) >= 2:
                    target = " ".join(rest[1:])
                    if target not in watches:
                        return CommandResult(f"autolog: {target} not watched")
                    watches = [t for t in watches if t != target]
                    self.bridge.set_telem_watches(watches)
                    return CommandResult(f"✓ autolog removed: {target}")
                return CommandResult(
                    "usage: !mesh autolog [add <name> | remove <name>]"
                )

            if cmd == "chart":
                if not rest:
                    return CommandResult("usage: !mesh chart <name> [hours]")
                target = rest[0]
                hours = 24.0
                if len(rest) >= 2:
                    try:
                        hours = float(rest[1])
                    except ValueError:
                        return CommandResult("hours must be a number (e.g. 24, 48, 0.5)")
                hours = max(0.1, min(hours, 720.0))
                import time as _time
                since = _time.time() - hours * 3600
                rows = self.bridge.telemetrylog.query(target=target, since=since)
                if not rows:
                    # fallback: no data for this target/window — maybe user passed pubkey prefix
                    # try generic contains on target name
                    rows = [
                        r for r in self.bridge.telemetrylog.query(since=since)
                        if target.lower() in str(r.get("target") or "").lower()
                    ]
                if not rows:
                    avail = self.bridge.telemetrylog.targets()
                    hint = ("known targets: " + ", ".join(avail)) if avail else \
                           "no telemetry logged yet — try `!mesh autolog add <name>` first"
                    return CommandResult(
                        f"no data for '{target}' in the last {hours:g} h.\n{hint}"
                    )
                try:
                    from .chart import render_chart
                    png, w, h = render_chart(rows, target=target, hours=hours)
                except ImportError:
                    return CommandResult(
                        "chart dependencies missing — install matplotlib in the bridge venv "
                        "(`pip install matplotlib`) and restart the service."
                    )
                except Exception as exc:
                    log.exception("chart render failed")
                    return CommandResult(f"chart render failed: {exc!r}")
                # upload + post to whoever issued the command
                target_room = source_room or self.bridge.control_room()
                if not target_room:
                    return CommandResult("no room to post the chart to")
                caption = f"{target} — last {hours:g} h ({len(rows)} samples)"
                try:
                    await self.bridge.matrix.send_image(
                        target_room,
                        png,
                        filename=f"mesh-telem-{target.replace(' ', '_')}-{int(hours)}h.png",
                        mime_type="image/png",
                        width=w, height=h,
                        caption=caption,
                    )
                except Exception as exc:
                    log.exception("chart upload failed")
                    return CommandResult(f"chart upload failed: {exc!r}")
                # Suppress further text; the image IS the reply
                return CommandResult("", target_room=target_room)

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
