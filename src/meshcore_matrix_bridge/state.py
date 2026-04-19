"""Tiny JSON-backed state store (bridge room id, channel cursor hashes, ...)."""
from __future__ import annotations

import json
from pathlib import Path
from threading import RLock
from typing import Any


class State:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if self.path.is_file():
            try:
                self._data: dict[str, Any] = json.loads(self.path.read_text("utf-8"))
            except Exception:
                self._data = {}
        else:
            self._data = {}

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._flush()

    def update(self, **kwargs: Any) -> None:
        with self._lock:
            self._data.update(kwargs)
            self._flush()

    def _flush(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True, default=str), encoding="utf-8")
        tmp.replace(self.path)
