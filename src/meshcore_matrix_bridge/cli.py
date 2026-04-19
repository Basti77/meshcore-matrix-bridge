"""Standalone CLI mode (no Matrix) — for terminal send/receive testing.

Usage examples:
  python -m meshcore_matrix_bridge.cli --port /dev/ttyUSB0 contacts
  python -m meshcore_matrix_bridge.cli --port /dev/ttyUSB0 channels
  python -m meshcore_matrix_bridge.cli --port /dev/ttyUSB0 fetch --limit 100
  python -m meshcore_matrix_bridge.cli --port /dev/ttyUSB0 dm Alice "hi there"
  python -m meshcore_matrix_bridge.cli --port /dev/ttyUSB0 send 0 "hallo #public"
  python -m meshcore_matrix_bridge.cli --port /dev/ttyUSB0 listen
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .meshnode import MeshNode


def _args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="meshcore-matrix-bridge-cli")
    ap.add_argument("--transport", choices=["serial", "ble"], default="serial")
    ap.add_argument("--port", default="/dev/ttyACM0",
                    help="serial device path, or BLE address (use 'scan' to auto-discover)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--ble-name", default=None, help="optional BLE name filter")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("contacts")
    sub.add_parser("channels")
    sub.add_parser("status")

    f = sub.add_parser("fetch")
    f.add_argument("--limit", type=int, default=200)

    p = sub.add_parser("public")
    p.add_argument("--limit", type=int, default=200)

    dm = sub.add_parser("dm")
    dm.add_argument("target")
    dm.add_argument("text", nargs="+")

    snd = sub.add_parser("send")
    snd.add_argument("channel_idx", type=int)
    snd.add_argument("text", nargs="+")

    sub.add_parser("listen")

    return ap.parse_args()


async def _run(a: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    node = MeshNode(a.port, a.baud, auto_reconnect=False,
                    transport=a.transport, ble_name_filter=a.ble_name)
    await node.connect()
    try:
        if a.cmd == "contacts":
            out = await node.list_contacts()
            _emit(a, out, lambda: _fmt_contacts(out))
        elif a.cmd == "channels":
            out = await node.list_channels()
            _emit(a, out, lambda: _fmt_channels(out))
        elif a.cmd == "status":
            out = await node.self_info()
            _emit(a, out, lambda: _fmt_kv(out))
        elif a.cmd in ("fetch", "public"):
            batch = await node.fetch_backlog(limit=a.limit)
            if a.cmd == "public":
                chans = await node.list_channels()
                public_idx = 0
                for ch in chans:
                    if (ch.get("channel_name") or "").lstrip("#").lower() == "public":
                        public_idx = ch.get("channel_idx")
                        break
                batch = [
                    (k, p) for (k, p) in batch
                    if k == "chan" and p.get("channel_idx") == public_idx
                ]
            _emit(a, batch, lambda: _fmt_batch(batch))
        elif a.cmd == "dm":
            r = await node.send_dm(a.target, " ".join(a.text))
            _emit(a, r, lambda: ("✓ " if r["ok"] else "✗ ") + (r.get("error") or "ok"))
        elif a.cmd == "send":
            r = await node.send_channel(a.channel_idx, " ".join(a.text))
            _emit(a, r, lambda: ("✓ " if r["ok"] else "✗ ") + (r.get("error") or "ok"))
        elif a.cmd == "listen":
            # live-listen: auto-fetch + print
            async def on_dm(p):
                print(f"[DM {p.get('pubkey_prefix','')[:12]}] {p.get('text','')}")
            async def on_ch(p):
                print(f"[CH#{p.get('channel_idx')}] {p.get('text','')}")
            node.on_dm(on_dm)
            node.on_channel(on_ch)
            await node.start_auto_fetch()
            print("listening — Ctrl-C to quit")
            try:
                while True:
                    await asyncio.sleep(60)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
        return 0
    finally:
        await node.disconnect()


def _fmt_contacts(contacts) -> str:
    if not contacts:
        return "(no contacts)"
    lines = [f"{len(contacts)} contact(s):"]
    for c in contacts:
        name = c.get("adv_name") or "(unnamed)"
        pk = (c.get("public_key") or "")[:12]
        path = c.get("out_path_len", "?")
        lines.append(f"  {name:<22} {pk}  pathlen={path}")
    return "\n".join(lines)


def _fmt_channels(chans) -> str:
    if not chans:
        return "(no channels)"
    lines = [f"{len(chans)} channel(s):"]
    for ch in chans:
        lines.append(f"  #{ch.get('channel_idx'):<2} {ch.get('channel_name') or '(unnamed)'}")
    return "\n".join(lines)


def _fmt_kv(d: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in d.items())


def _fmt_batch(batch) -> str:
    if not batch:
        return "(no pending messages)"
    lines = []
    for kind, payload in batch:
        if kind == "dm":
            lines.append(f"[DM {payload.get('pubkey_prefix','')[:12]}] {payload.get('text','')}")
        else:
            lines.append(f"[CH#{payload.get('channel_idx')}] {payload.get('text','')}")
    return "\n".join(lines)


def _emit(a, obj, text_fn) -> None:
    if a.json:
        print(json.dumps(obj, indent=2, default=str))
    else:
        print(text_fn())


def main() -> int:
    try:
        return asyncio.run(_run(_args()))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
