"""Append-only telemetry log + query helpers.

Stores one JSON record per poll on disk (JSONL), cheap to tail, cheap to
filter by time window. Rotated at 10 MB → ``.jsonl.1``. Designed for a
handful of nodes polled every few minutes — single-digit MB per month
even with aggressive sampling.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Iterable


log = logging.getLogger(__name__)


_MAX_BYTES = 10 * 1024 * 1024


class TelemetryLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(
        self,
        target: str,
        sensors: list[dict[str, Any]],
        path_len: Any = None,
        pubkey_prefix: str | None = None,
        ts: float | None = None,
    ) -> None:
        if not sensors:
            return
        # flatten LPP list to dict channel-indexed: {"voltage@1": 4.07, ...}
        flat: dict[str, Any] = {}
        for s in sensors:
            if not isinstance(s, dict):
                continue
            typ = s.get("type")
            val = s.get("value")
            ch = s.get("channel") or 1
            if typ is None or val is None:
                continue
            key = f"{typ}@{ch}" if ch != 1 else str(typ)
            flat[key] = val
        if not flat:
            return
        row = {
            "ts": ts if ts is not None else time.time(),
            "target": target,
            "pubkey_prefix": pubkey_prefix,
            "path_len": path_len,
            "values": flat,
        }
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                if self.path.exists() and self.path.stat().st_size > _MAX_BYTES:
                    rot = self.path.with_suffix(self.path.suffix + ".1")
                    try:
                        if rot.exists():
                            rot.unlink()
                        os.rename(self.path, rot)
                    except OSError as e:
                        log.warning("telemetrylog rotate failed: %s", e)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                log.exception("telemetrylog append failed")

    def query(
        self,
        target: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return rows matching filters. Reads both current file and .1 rotation."""
        targ_lc = target.lower() if target else None
        out: list[dict[str, Any]] = []
        for p in (self.path.with_suffix(self.path.suffix + ".1"), self.path):
            if not p.exists():
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except Exception:
                            continue
                        ts = row.get("ts") or 0
                        if since is not None and ts < since:
                            continue
                        if until is not None and ts > until:
                            continue
                        if targ_lc:
                            t = str(row.get("target") or "").lower()
                            pk = str(row.get("pubkey_prefix") or "").lower()
                            if targ_lc != t and not pk.startswith(targ_lc):
                                continue
                        out.append(row)
            except Exception:
                log.exception("telemetrylog read failed for %s", p)
        out.sort(key=lambda r: r.get("ts") or 0)
        if limit is not None and limit > 0:
            out = out[-limit:]
        return out

    def targets(self) -> list[str]:
        """List of distinct target labels seen in the log (most recent first)."""
        seen: dict[str, float] = {}
        for p in (self.path.with_suffix(self.path.suffix + ".1"), self.path):
            if not p.exists():
                continue
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            row = json.loads(line)
                        except Exception:
                            continue
                        t = row.get("target")
                        ts = row.get("ts") or 0
                        if t:
                            seen[t] = max(seen.get(t, 0), ts)
            except Exception:
                pass
        return [t for t, _ in sorted(seen.items(), key=lambda kv: -kv[1])]
