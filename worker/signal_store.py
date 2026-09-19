from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any


class DailySignalStore:
    """Persistent, day-scoped signal store.

    A symbol/timeframe is written only once per direction per trading day.
    The first confirmed timestamp is preserved for the entire day.
    """

    def __init__(self, path: str | None = None):
        self.path = Path(path or os.getenv("SIGNAL_STORE_PATH", "data/signals.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    @staticmethod
    def _today() -> str:
        return datetime.now().astimezone().date().isoformat()

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict[str, list[dict[str, Any]]]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.path)

    def add_confirmed(self, signal: dict[str, Any]) -> bool:
        if signal.get("state") != "CONFIRMED":
            return False

        day = self._today()
        symbol = str(signal["symbol"])
        timeframe = int(signal["timeframe"])
        direction = str(signal["direction"])
        key = f"{symbol}|{timeframe}|{direction}"

        with self._lock:
            data = self._load()
            day_rows = data.setdefault(day, [])
            if any(row.get("dedupe_key") == key for row in day_rows):
                return False

            row = dict(signal)
            row["dedupe_key"] = key
            row["first_confirmed_at"] = row.get("timestamp")
            day_rows.append(row)
            day_rows.sort(key=lambda x: x.get("first_confirmed_at") or "")
            self._save(data)
            return True

    def today(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._load().get(self._today(), [])
