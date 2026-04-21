"""Persistent append-only log of silently dropped RX messages.

The bridge drops channel messages when ``relay`` is off, when no Matrix
room is bound, or when a Matrix send fails. The user needs to be able
to investigate *why* a channel is quiet after a bridge restart, so we
persist drops to disk — not the full RX stream (Matrix already has that
for relayed messages).

File format: JSONL, one record per line::

    {"t": 1745221234, "kind": "chan", "idx": 7, "reason": "relay-off",
     "text": "…", "snr": 12.25, "path_len": 2, "pubkey_prefix": "ab12…",
     "sender_ts": 1745221230}

Rotation: when the active file grows past ``max_bytes``, it is renamed
to ``<name>.1`` (overwriting any previous ``.1``) and a fresh file is
opened. We keep one generation on disk, giving roughly ``2 * max_bytes``
of history — enough to survive a restart plus a few hours of activity.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from pathlib import Path
from threading import RLock
from typing import Any, Iterable


log = logging.getLogger(__name__)

_SAMPLE_CAP = 20  # per channel / DM ringbuffer size


class DropLog:
    def __init__(self, path: Path, max_bytes: int = 2 * 1024 * 1024) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self._lock = RLock()

        # In-memory materialisation — rebuilt at startup from on-disk JSONL
        self.counters_chan: dict[int, int] = {}
        self.counters_dm: int = 0
        self.samples_chan: dict[int, deque] = {}
        self.samples_dm: deque = deque(maxlen=_SAMPLE_CAP)

        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        for p in (self._rotated_path(), self.path):
            if not p.is_file():
                continue
            try:
                with p.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        self._ingest(rec)
            except Exception:
                log.exception("reading drop log %s failed", p)
        total_chan = sum(self.counters_chan.values())
        log.info(
            "droplog: restored %d channel drops across %d channel(s), %d DM drops",
            total_chan, len(self.counters_chan), self.counters_dm,
        )

    def _ingest(self, rec: dict[str, Any]) -> None:
        kind = rec.get("kind")
        if kind == "chan":
            idx = rec.get("idx")
            if idx is None:
                return
            idx = int(idx)
            self.counters_chan[idx] = self.counters_chan.get(idx, 0) + 1
            buf = self.samples_chan.setdefault(idx, deque(maxlen=_SAMPLE_CAP))
            buf.append(rec)
        elif kind == "dm":
            self.counters_dm += 1
            self.samples_dm.append(rec)

    def _rotated_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".1")

    # ------------------------------------------------------------------
    def record_chan(
        self,
        idx: int | None,
        reason: str,
        payload: dict[str, Any],
    ) -> None:
        if idx is None:
            return
        rec = {
            "t": int(time.time()),
            "kind": "chan",
            "idx": int(idx),
            "reason": reason,
            "text": payload.get("text", ""),
            "snr": payload.get("SNR"),
            "path_len": payload.get("path_len"),
            "pubkey_prefix": (payload.get("pubkey_prefix") or "")[:12],
            "sender_ts": payload.get("sender_timestamp"),
        }
        self._append(rec)
        self._ingest(rec)

    def record_dm(self, reason: str, payload: dict[str, Any]) -> None:
        rec = {
            "t": int(time.time()),
            "kind": "dm",
            "reason": reason,
            "text": payload.get("text", ""),
            "snr": payload.get("SNR"),
            "path_len": payload.get("path_len"),
            "pubkey_prefix": (payload.get("pubkey_prefix") or "")[:12],
            "sender_ts": payload.get("sender_timestamp"),
        }
        self._append(rec)
        self._ingest(rec)

    # ------------------------------------------------------------------
    def _append(self, rec: dict[str, Any]) -> None:
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                if self.path.is_file() and self.path.stat().st_size >= self.max_bytes:
                    self._rotate()
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                log.exception("appending to drop log failed")

    def _rotate(self) -> None:
        try:
            rotated = self._rotated_path()
            if rotated.exists():
                rotated.unlink()
            os.rename(self.path, rotated)
            log.info("droplog: rotated %s -> %s", self.path, rotated)
        except Exception:
            log.exception("drop log rotation failed")

    # ------------------------------------------------------------------
    def snapshot_channels(self) -> dict[int, dict[str, Any]]:
        with self._lock:
            out: dict[int, dict[str, Any]] = {}
            for idx, cnt in self.counters_chan.items():
                out[idx] = {
                    "dropped": cnt,
                    "samples": list(self.samples_chan.get(idx, [])),
                }
            return out

    def snapshot_dm(self) -> dict[str, Any]:
        with self._lock:
            return {
                "dropped": self.counters_dm,
                "samples": list(self.samples_dm),
            }
