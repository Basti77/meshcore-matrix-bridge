"""Thin wrapper around the `meshcore` Python library.

Supports both USB serial and BLE transport. BLE is needed for the common
RAK4631 Companion firmware where USB-CDC is only debug output and the real
Companion protocol runs over the Nordic UART BLE service.

Responsibilities:
 - open connection to a MeshCore Companion node (serial *or* BLE)
 - expose high-level operations used by the bridge (list contacts/channels,
   send DM, send channel msg, fetch backlog from the node)
 - fan-out incoming RX events to registered callbacks
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from meshcore import MeshCore, EventType  # type: ignore[import-not-found]


log = logging.getLogger(__name__)

RxCallback = Callable[[dict[str, Any]], Awaitable[None]]


class MeshNode:
    """Lifecycle wrapper for a MeshCore Companion node.

    Supported transports:
      - ``serial`` — classic USB-CDC (``/dev/ttyACM0``, ``/dev/ttyUSB0``, ...)
      - ``ble``    — Bluetooth Low Energy (address or device name)

    Which one to use is selected by ``transport``. For BLE the ``port``
    argument is interpreted as the BLE address or device name to search for.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        auto_reconnect: bool = True,
        transport: str = "serial",
        ble_name_filter: str | None = None,
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.auto_reconnect = auto_reconnect
        self.transport = transport.lower()
        self.ble_name_filter = ble_name_filter
        self.mc: Optional[MeshCore] = None
        self._dm_cbs: list[RxCallback] = []
        self._chan_cbs: list[RxCallback] = []
        self._ready = asyncio.Event()

    # ----- lifecycle ---------------------------------------------------

    async def connect(self) -> None:
        if self.transport == "ble":
            # ``port`` is the BLE address (preferred) or None to scan for name.
            addr = self.port if self.port and self.port != "scan" else None
            log.info(
                "Opening BLE to %s (name-filter=%r)",
                addr or "(scan)", self.ble_name_filter,
            )
            self.mc = await MeshCore.create_ble(
                address=addr,
                name=self.ble_name_filter,
                debug=False,
                auto_reconnect=self.auto_reconnect,
                default_timeout=10.0,
            )
            if self.mc is None:
                raise RuntimeError(
                    f"MeshCore.create_ble returned None (addr={addr!r} "
                    f"name_filter={self.ble_name_filter!r}) — no Companion node found. "
                    f"Is the node advertising? Is the phone disconnected "
                    f"(only one BLE Central allowed at a time)?"
                )
        else:
            log.info("Opening serial %s @ %d", self.port, self.baudrate)
            self.mc = await MeshCore.create_serial(
                port=self.port,
                baudrate=self.baudrate,
                debug=False,
                auto_reconnect=self.auto_reconnect,
                default_timeout=10.0,
            )
            if self.mc is None:
                raise RuntimeError(
                    f"MeshCore.create_serial returned None on {self.port} — "
                    "the firmware might be BLE-only (typical for RAK4631 "
                    "Companion builds). Try MESHCORE_TRANSPORT=ble."
                )
        self.mc.subscribe(EventType.CONTACT_MSG_RECV, self._on_dm)
        self.mc.subscribe(EventType.CHANNEL_MSG_RECV, self._on_chan)
        self._ready.set()
        log.info("Connected to MeshCore node (%s)", self.transport)

    async def start_auto_fetch(self) -> None:
        assert self.mc is not None
        await self.mc.start_auto_message_fetching()

    async def stop_auto_fetch(self) -> None:
        if self.mc is not None:
            try:
                await self.mc.stop_auto_message_fetching()
            except Exception:
                pass

    async def disconnect(self) -> None:
        await self.stop_auto_fetch()
        if self.mc is not None:
            try:
                await self.mc.disconnect()
            except Exception:
                pass
        self._ready.clear()

    # ----- subscriptions -----------------------------------------------

    def on_dm(self, cb: RxCallback) -> None:
        self._dm_cbs.append(cb)

    def on_channel(self, cb: RxCallback) -> None:
        self._chan_cbs.append(cb)

    async def _on_dm(self, event: Any) -> None:
        for cb in list(self._dm_cbs):
            try:
                await cb(event.payload)
            except Exception:
                log.exception("DM callback failed")

    async def _on_chan(self, event: Any) -> None:
        for cb in list(self._chan_cbs):
            try:
                await cb(event.payload)
            except Exception:
                log.exception("Channel callback failed")

    # ----- queries ------------------------------------------------------

    async def list_contacts(self) -> list[dict[str, Any]]:
        assert self.mc is not None
        r = await self.mc.commands.get_contacts()
        if r.type == EventType.ERROR or not isinstance(r.payload, dict):
            return []
        out: list[dict[str, Any]] = []
        for key, c in r.payload.items():
            c2 = dict(c)
            c2.setdefault("public_key", key)
            out.append(c2)
        out.sort(key=lambda c: (c.get("adv_name") or "").lower())
        return out

    async def list_channels(self, max_index: int = 16) -> list[dict[str, Any]]:
        assert self.mc is not None
        out: list[dict[str, Any]] = []
        for idx in range(max_index):
            r = await self.mc.commands.get_channel(idx)
            if r.type == EventType.ERROR:
                break
            if isinstance(r.payload, dict):
                out.append(dict(r.payload))
        return out

    # ----- actions ------------------------------------------------------

    async def send_dm(self, target: str, text: str) -> dict[str, Any]:
        """target: adv_name OR hex public-key prefix."""
        assert self.mc is not None
        contact = self.mc.get_contact_by_name(target)
        if contact is None:
            contact = self.mc.get_contact_by_key_prefix(target)
        if contact is None:
            return {"ok": False, "error": f"contact '{target}' not found"}
        r = await self.mc.commands.send_msg_with_retry(
            contact, text, max_attempts=3, max_flood_attempts=2, flood_after=2,
        )
        if r is None:
            return {"ok": False, "error": "no ACK"}
        return {"ok": True, "info": r.payload if hasattr(r, "payload") else None}

    async def send_channel(self, channel_idx: int, text: str) -> dict[str, Any]:
        assert self.mc is not None
        r = await self.mc.commands.send_chan_msg(channel_idx, text)
        if r.type == EventType.ERROR:
            return {"ok": False, "error": str(r.payload)}
        return {"ok": True}

    async def fetch_backlog(self, limit: int = 200) -> list[tuple[str, dict[str, Any]]]:
        """Drain the node's pending-queue manually.

        Returns [(kind, payload), ...] where kind is 'dm' or 'chan'.
        Stops on NO_MORE_MSGS / ERROR / limit.
        """
        assert self.mc is not None
        out: list[tuple[str, dict[str, Any]]] = []
        for _ in range(limit):
            ev = await self.mc.commands.get_msg()
            t = getattr(ev, "type", None)
            if t == EventType.CONTACT_MSG_RECV:
                out.append(("dm", ev.payload))
            elif t == EventType.CHANNEL_MSG_RECV:
                out.append(("chan", ev.payload))
            elif t in (EventType.NO_MORE_MSGS, EventType.ERROR):
                break
            else:
                # ignore unrelated events (e.g. OK)
                continue
        return out

    # ----- misc ---------------------------------------------------------

    async def self_info(self) -> dict[str, Any]:
        assert self.mc is not None
        info: dict[str, Any] = {}
        try:
            r = await self.mc.commands.send_device_query()
            if hasattr(r, "payload") and isinstance(r.payload, dict):
                info.update(r.payload)
        except Exception:
            pass
        try:
            bat = await self.mc.commands.get_bat()
            if hasattr(bat, "payload") and isinstance(bat.payload, dict):
                info["battery"] = bat.payload
        except Exception:
            pass
        return info
