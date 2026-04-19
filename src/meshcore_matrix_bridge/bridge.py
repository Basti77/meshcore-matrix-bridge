"""Bridge entry point.

Wires MeshCore serial, Matrix client, commands, and room bindings.

Bindings model (persisted in state.json under ``channels``):

    {
      "0": {"room_id": "!xxx:server", "alias": "#mesh-public:server",
            "relay": false,            # forward RX to room automatically?
            "name": "public"},
      ...
    }

The control room is the DM the bot auto-creates with the first allowed user.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import sys
from pathlib import Path
from typing import Any, Optional

from .commands import CommandHandler, fmt_msg
from .config import BridgeConfig, load_env_files
from .matrixbot import MatrixBot
from .meshnode import MeshNode
from .state import State
from .textsplit import split_for_radio


_ALIAS_RE = re.compile(r"[^a-z0-9_\-]+")


def _setup_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _norm_alias(s: str) -> str:
    s = s.lower().lstrip("#").lstrip("&")
    s = _ALIAS_RE.sub("-", s).strip("-")
    return s or "channel"


class Bridge:
    def __init__(self, cfg: BridgeConfig) -> None:
        self.cfg = cfg
        self.log = logging.getLogger("bridge")
        self.state = State(cfg.state_path)
        self.node = MeshNode(
            cfg.meshcore_port,
            cfg.meshcore_baudrate,
            cfg.meshcore_auto_reconnect,
            transport=cfg.meshcore_transport,
            ble_name_filter=cfg.meshcore_ble_name,
        )
        self.matrix = MatrixBot(
            cfg.matrix_homeserver,
            cfg.matrix_user_id,
            cfg.matrix_access_token,
            cfg.matrix_device_id,
            cfg.matrix_allowed_users,
        )
        self.handler = CommandHandler(self.node, self, prefix=cfg.command_prefix)

    # ===== persistent state accessors ================================

    def control_room(self) -> str | None:
        return self.cfg.matrix_room_id or self.state.get("control_room_id")

    def get_channel_bindings(self) -> dict[str, dict[str, Any]]:
        return dict(self.state.get("channels", {}) or {})

    def _channel_room(self, idx: int) -> str | None:
        b = self.get_channel_bindings().get(str(idx))
        return (b or {}).get("room_id")

    def _room_to_channel(self, room_id: str) -> int | None:
        for k, v in self.get_channel_bindings().items():
            if v.get("room_id") == room_id:
                try:
                    return int(k)
                except ValueError:
                    return None
        return None

    def _save_binding(self, idx: int, **fields: Any) -> None:
        ch = self.get_channel_bindings()
        b = ch.get(str(idx), {})
        b.update(fields)
        ch[str(idx)] = b
        self.state.set("channels", ch)

    def unbind_channel(self, idx: int) -> bool:
        ch = self.get_channel_bindings()
        if str(idx) not in ch:
            return False
        ch.pop(str(idx))
        self.state.set("channels", ch)
        return True

    def set_channel_relay(self, idx: int, on: bool) -> bool:
        ch = self.get_channel_bindings()
        if str(idx) not in ch:
            return False
        ch[str(idx)]["relay"] = bool(on)
        self.state.set("channels", ch)
        return True

    # ===== operations ================================================

    async def ensure_control_room(self) -> str:
        rid = self.control_room()
        if rid:
            return rid
        if not self.cfg.matrix_allowed_users:
            raise RuntimeError("No MATRIX_ALLOWED_USERS configured; cannot auto-create DM")
        invitee = self.cfg.matrix_allowed_users[0]
        self.log.info("Creating control DM with %s", invitee)
        rid = await self.matrix.create_dm(invitee, name="MeshCore Bridge")
        self.state.set("control_room_id", rid)
        return rid

    async def bind_channel(
        self, idx: int, alias_hint: str | None = None
    ) -> tuple[str, str | None, bool]:
        """Ensure a public, read-along Matrix room exists for channel ``idx``.

        Returns ``(room_id, full_alias_or_None, created_flag)``."""
        existing = self._channel_room(idx)
        if existing:
            return existing, None, False

        # find channel name from the node
        chans = await self.node.list_channels()
        chan = next((c for c in chans if c.get("channel_idx") == idx), None)
        name = (chan or {}).get("channel_name") or f"ch{idx}"

        alias_local = _norm_alias(alias_hint or f"mesh-{name}")
        full_alias = f"#{alias_local}:{self.matrix.server_name}" if self.matrix.server_name else None

        room_id = await self.matrix.create_channel_room(
            name=f"MeshCore #{name}",
            alias_localpart=alias_local,
            topic=(
                f"MeshCore channel #{idx} · {name}. Read-along — only authorized "
                f"operators can transmit. Messages here are broadcast to the mesh."
            ),
            writers=list(self.cfg.matrix_allowed_users),
        )

        # invite primary allowed user so the room shows up in their client immediately
        for u in self.cfg.matrix_allowed_users:
            try:
                await self.matrix.invite(room_id, u)
            except Exception:
                pass

        self._save_binding(idx, room_id=room_id, alias=full_alias, name=name, relay=False)
        try:
            await self.matrix.send(
                room_id,
                f"🟢 Channel #{idx} ({name}) bound. Messages here transmit on the mesh.",
                notice=True,
            )
        except Exception:
            pass
        return room_id, full_alias, True

    async def send_channel_split(self, idx: int, text: str) -> dict[str, Any]:
        parts = split_for_radio(text)
        if not parts:
            return {"ok": False, "error": "empty text"}
        for p in parts:
            r = await self.node.send_channel(idx, p)
            if not r["ok"]:
                return r
            await asyncio.sleep(0.8)  # small delay between fragments
        return {"ok": True, "parts": len(parts)}

    async def send_dm(self, target: str, text: str) -> dict[str, Any]:
        parts = split_for_radio(text)
        if not parts:
            return {"ok": False, "error": "empty text"}
        last = {"ok": False, "error": "no parts"}
        for p in parts:
            last = await self.node.send_dm(target, p)
            if not last["ok"]:
                return last
            await asyncio.sleep(0.8)
        return last

    async def drain_backlog(
        self,
        only_channel: int | None = None,
        only_public: bool = False,
        limit: int = 200,
    ) -> int:
        batch = await self.node.fetch_backlog(limit=limit)
        if only_public:
            chans = await self.node.list_channels()
            public_idx = next(
                (c.get("channel_idx") for c in chans
                 if (c.get("channel_name") or "").lstrip("#").lower() == "public"),
                0,
            )
            batch = [
                (k, p) for (k, p) in batch
                if k == "chan" and p.get("channel_idx") == public_idx
            ]
        elif only_channel is not None:
            batch = [
                (k, p) for (k, p) in batch
                if k == "chan" and p.get("channel_idx") == only_channel
            ]
        count = 0
        for kind, payload in batch:
            await self._deliver_rx(kind, payload, force=True)
            count += 1
        return count

    # ===== incoming (mesh → matrix) ==================================

    async def _deliver_rx(self, kind: str, payload: dict[str, Any], force: bool = False) -> None:
        plain, html = fmt_msg(kind, payload, self.node)
        target: str | None
        if kind == "dm":
            target = self.control_room()
        else:
            idx = payload.get("channel_idx")
            target = self._channel_room(int(idx)) if idx is not None else None
            if not force:
                bindings = self.get_channel_bindings()
                b = bindings.get(str(idx), {})
                if not b.get("relay", False):
                    # just log, don't forward — user can !mesh fetch later
                    self.log.info("RX #%s (relay off): %s", idx, payload.get("text", ""))
                    return
            if target is None:
                # no room bound → fall back to control room
                target = self.control_room()
        if target:
            try:
                await self.matrix.send_html(target, plain, html)
            except Exception:
                self.log.exception("send to %s failed", target)

    # ===== incoming (matrix → mesh) ==================================

    async def _on_matrix_msg(self, room_id: str, sender: str, body: str) -> None:
        # 1. Commands go to the handler (from anywhere, but only allowed users)
        if self.handler.matches(body):
            if sender not in self.cfg.matrix_allowed_users:
                return
            self.log.info("cmd from %s in %s: %s", sender, room_id, body.strip()[:120])
            res = await self.handler.dispatch(body, source_room=room_id)
            if res.html:
                await self.matrix.send_html(room_id, res.plain, res.html, notice=True)
            else:
                await self.matrix.send(room_id, res.plain, notice=True)
            return

        # 2. Channel-room messages → transmit on the mesh
        idx = self._room_to_channel(room_id)
        if idx is None:
            return  # not a bound channel room; ignore silently

        # power-levels should block non-authorized senders, but double-check:
        if sender not in self.cfg.matrix_allowed_users:
            self.log.warning("Blocking TX from unauthorized sender %s in room %s", sender, room_id)
            return

        self.log.info("matrix->mesh #%d from %s: %s", idx, sender, body[:80])
        r = await self.send_channel_split(idx, body)
        if not r["ok"]:
            await self.matrix.send(
                room_id, f"✗ mesh TX failed on #{idx}: {r.get('error')}", notice=True
            )

    # ===== main ======================================================

    async def run(self) -> int:
        self.matrix.on_message(self._on_matrix_msg)
        self.node.on_dm(lambda p: self._deliver_rx("dm", p))
        self.node.on_channel(lambda p: self._deliver_rx("chan", p))

        async def _on_status(status: str, detail: str) -> None:
            rid = self.control_room()
            if not rid:
                return
            if status == "offline":
                body = f"🔴 MeshCore-Node OFFLINE ({detail})"
            elif status == "online":
                body = f"🟢 MeshCore-Node wieder ONLINE ({detail})"
            else:
                body = f"ℹ️ Node-Status: {status} ({detail})"
            try:
                await self.matrix.send(rid, body, notice=True)
            except Exception:
                self.log.exception("send status notice failed")
        self.node.on_status(_on_status)

        self.log.info("Connecting to MeshCore on %s", self.cfg.meshcore_port)
        await self.node.connect()
        if self.cfg.auto_fetch_messages:
            await self.node.start_auto_fetch()

        matrix_task = asyncio.create_task(self.matrix.start(), name="matrix-sync")
        await asyncio.sleep(3)  # let initial sync run
        try:
            ctrl = await self.ensure_control_room()
            await self.matrix.send(
                ctrl,
                f"🟢 meshcore-matrix-bridge online on {self.cfg.meshcore_port}. "
                f"Type `{self.cfg.command_prefix} help`.",
                notice=True,
            )
        except Exception:
            self.log.exception("Failed to ensure control room")

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
        await stop.wait()

        self.log.info("Shutting down")
        matrix_task.cancel()
        await self.node.disconnect()
        await self.matrix.close()
        return 0


def main() -> int:
    _setup_logging()
    env_paths = [
        Path(p) for p in os.environ.get(
            "MESH_BRIDGE_ENV_FILES",
            "/home/klempi/.meshcore-bridge-secrets/matrix.env:"
            "/home/klempi/.meshcore-bridge-secrets/bridge.env",
        ).split(":") if p.strip()
    ]
    load_env_files(env_paths)
    cfg = BridgeConfig.from_env()
    try:
        return asyncio.run(Bridge(cfg).run())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
