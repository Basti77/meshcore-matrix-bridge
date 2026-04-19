"""Configuration loader for the bridge.

Reads environment variables (optionally from one or more .env files) and
validates them into a frozen dataclass. No secrets are hardcoded.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


def _load_env_file(path: Path) -> None:
    """Tiny .env parser (KEY=VALUE, comments with #). Does not overwrite
    variables already present in the environment."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def load_env_files(paths: Iterable[Path]) -> None:
    for p in paths:
        _load_env_file(Path(p))


@dataclass(frozen=True)
class BridgeConfig:
    # --- Matrix ---
    matrix_homeserver: str
    matrix_user_id: str
    matrix_access_token: str
    matrix_device_id: str
    matrix_allowed_users: tuple[str, ...]
    matrix_room_id: str | None  # optional: auto-use this room as bridge room

    # --- MeshCore node ---
    meshcore_transport: str       # "serial" | "ble"
    meshcore_port: str            # for serial: /dev/ttyACM0 ; for ble: address or "scan"
    meshcore_baudrate: int
    meshcore_ble_name: str | None # optional BLE name filter
    meshcore_auto_reconnect: bool

    # --- Bridge behaviour ---
    command_prefix: str           # default "!mesh"
    auto_fetch_messages: bool     # start auto-fetch on connect
    relay_channel_messages: bool  # forward channel RX to Matrix by default
    relay_channel_indexes: tuple[int, ...]  # which channels to relay (empty = none)
    state_path: Path              # JSON file for persistent state (room-id, last-fetch, etc.)

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        def req(name: str) -> str:
            v = os.environ.get(name)
            if not v:
                raise RuntimeError(f"Missing required env var: {name}")
            return v

        allowed = tuple(
            u.strip() for u in os.environ.get("MATRIX_ALLOWED_USERS", "").split(",") if u.strip()
        )
        relay_idx_raw = os.environ.get("MESH_RELAY_CHANNEL_INDEXES", "").strip()
        relay_idx: tuple[int, ...] = tuple(
            int(x) for x in relay_idx_raw.split(",") if x.strip().lstrip("-").isdigit()
        ) if relay_idx_raw else ()

        return cls(
            matrix_homeserver=req("MATRIX_HOMESERVER").rstrip("/"),
            matrix_user_id=req("MATRIX_USER_ID"),
            matrix_access_token=req("MATRIX_ACCESS_TOKEN"),
            matrix_device_id=req("MATRIX_DEVICE_ID"),
            matrix_allowed_users=allowed,
            matrix_room_id=os.environ.get("MATRIX_ROOM_ID") or None,
            meshcore_transport=os.environ.get("MESHCORE_TRANSPORT", "serial").lower(),
            meshcore_port=os.environ.get("MESHCORE_PORT", "/dev/ttyACM0"),
            meshcore_baudrate=int(os.environ.get("MESHCORE_BAUDRATE", "115200")),
            meshcore_ble_name=os.environ.get("MESHCORE_BLE_NAME") or None,
            meshcore_auto_reconnect=os.environ.get("MESHCORE_AUTO_RECONNECT", "1") == "1",
            command_prefix=os.environ.get("MESH_COMMAND_PREFIX", "!mesh"),
            auto_fetch_messages=os.environ.get("MESH_AUTO_FETCH", "1") == "1",
            relay_channel_messages=os.environ.get("MESH_RELAY_CHANNELS", "0") == "1",
            relay_channel_indexes=relay_idx,
            state_path=Path(os.environ.get("MESH_STATE_PATH", str(Path.home() / ".local/state/meshcore-matrix-bridge/state.json"))),
        )
