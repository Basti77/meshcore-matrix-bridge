"""Matrix client wrapper (matrix-nio, unencrypted).

Supports creating world-readable, public-join channel rooms with a power-level
layout that only lets explicit writers (plus the bot itself) send messages.
Everyone else can read along — "amateur radio" style.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Optional

from nio import (  # type: ignore[import-not-found]
    AsyncClient,
    AsyncClientConfig,
    InviteMemberEvent,
    LoginResponse,
    RoomMessageText,
    MatrixRoom,
    RoomPreset,
    RoomVisibility,
)


log = logging.getLogger(__name__)

MsgCallback = Callable[[str, str, str], Awaitable[None]]  # (room_id, sender, body)


class MatrixBot:
    def __init__(
        self,
        homeserver: str,
        user_id: str,
        access_token: str,
        device_id: str,
        allowed_users: tuple[str, ...],
    ) -> None:
        self.homeserver = homeserver
        self.user_id = user_id
        self.access_token = access_token
        self.device_id = device_id
        self.allowed_users = set(allowed_users)
        self.server_name = user_id.split(":", 1)[1] if ":" in user_id else ""

        cfg = AsyncClientConfig(encryption_enabled=False, store_sync_tokens=True)
        self.client = AsyncClient(homeserver, user_id, device_id=device_id, config=cfg)
        self.client.access_token = access_token
        self.client.user_id = user_id

        self._msg_cbs: list[MsgCallback] = []
        self._ready = asyncio.Event()

        self.client.add_event_callback(self._on_invite, InviteMemberEvent)
        self.client.add_event_callback(self._on_message, RoomMessageText)

    # ----- hooks --------------------------------------------------------

    def on_message(self, cb: MsgCallback) -> None:
        self._msg_cbs.append(cb)

    # ----- lifecycle ----------------------------------------------------

    async def start(self) -> None:
        log.info("Matrix sync_forever starting as %s", self.user_id)
        self._ready.set()
        await self.client.sync_forever(timeout=30000, full_state=False, loop_sleep_time=1000)

    async def close(self) -> None:
        try:
            await self.client.close()
        except Exception:
            pass

    # ----- actions ------------------------------------------------------

    async def invite(self, room_id: str, user_id: str) -> None:
        await self.client.room_invite(room_id, user_id)

    async def create_dm(self, invitee: str, name: str = "MeshCore Bridge") -> str:
        """Private control room (DM). Only bot + invitee, trusted_private_chat
        preset (both get PL 100)."""
        resp = await self.client.room_create(
            name=name,
            topic="MeshCore ↔ Matrix bridge control room",
            invite=[invitee],
            is_direct=True,
            preset=RoomPreset.trusted_private_chat,
        )
        return resp.room_id  # type: ignore[attr-defined]

    async def create_channel_room(
        self,
        *,
        name: str,                    # display name, e.g. "MeshCore #public"
        alias_localpart: str | None,  # e.g. "mesh-public" (None = no alias)
        topic: str,
        writers: list[str],           # MXIDs that should be allowed to send (PL 50)
    ) -> str:
        """Create a world-readable, public-join room where only ``writers`` (and
        the bot itself) can send messages."""
        # Power-level override:
        #   - events_default 50 → only PL ≥ 50 may send messages
        #   - users_default   0
        #   - bot             100 (full admin)
        #   - writers         50  (may send messages)
        users_pl: dict[str, int] = {self.user_id: 100}
        for w in writers:
            if w and w != self.user_id:
                users_pl[w] = 50
        power_override = {
            "users_default": 0,
            "events_default": 50,
            "state_default": 100,
            "invite": 50,
            "kick": 50,
            "ban": 80,
            "redact": 50,
            "users": users_pl,
        }
        initial_state = [
            {
                "type": "m.room.history_visibility",
                "state_key": "",
                "content": {"history_visibility": "world_readable"},
            },
            {
                "type": "m.room.guest_access",
                "state_key": "",
                "content": {"guest_access": "can_join"},
            },
        ]
        kwargs: dict[str, Any] = dict(
            name=name,
            topic=topic,
            preset=RoomPreset.public_chat,
            visibility=RoomVisibility.public,
            power_level_override=power_override,
            initial_state=initial_state,
        )
        if alias_localpart:
            kwargs["alias"] = alias_localpart
        resp = await self.client.room_create(**kwargs)
        if not getattr(resp, "room_id", None):
            raise RuntimeError(f"room_create failed: {resp!r}")
        return resp.room_id  # type: ignore[attr-defined]

    async def send(self, room_id: str, body: str, notice: bool = False) -> None:
        content = {
            "msgtype": "m.notice" if notice else "m.text",
            "body": body,
        }
        await self.client.room_send(
            room_id=room_id, message_type="m.room.message", content=content, ignore_unverified_devices=True,
        )

    async def send_html(self, room_id: str, plain: str, html: str, notice: bool = False) -> None:
        content = {
            "msgtype": "m.notice" if notice else "m.text",
            "body": plain,
            "format": "org.matrix.custom.html",
            "formatted_body": html,
        }
        await self.client.room_send(
            room_id=room_id, message_type="m.room.message", content=content, ignore_unverified_devices=True,
        )

    # ----- callbacks ----------------------------------------------------

    async def _on_invite(self, room: MatrixRoom, event: InviteMemberEvent) -> None:
        if event.state_key != self.user_id:
            return
        if event.sender not in self.allowed_users:
            log.warning("Ignoring invite from %s (not in allowlist)", event.sender)
            return
        log.info("Accepting invite to %s from %s", room.room_id, event.sender)
        await self.client.join(room.room_id)

    async def _on_message(self, room: MatrixRoom, event: RoomMessageText) -> None:
        if event.sender == self.user_id:
            return
        for cb in list(self._msg_cbs):
            try:
                await cb(room.room_id, event.sender, event.body)
            except Exception:
                log.exception("message callback failed")
