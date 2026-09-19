from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests

from .candles import candles_to_frame


@dataclass
class UpstoxClient:
    access_token: str | None = None
    base_url: str = "https://api.upstox.com"

    def __post_init__(self):
        self.access_token = self.access_token or os.getenv("UPSTOX_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError("UPSTOX_ACCESS_TOKEN is required")

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        r = requests.get(self.base_url + path, headers=self.headers, params=params, timeout=20)
        r.raise_for_status()
        return r.json()

    def historical(self, instrument_key: str, unit: str, interval: int, to_date: str, from_date: str | None = None):
        encoded = requests.utils.quote(instrument_key, safe="")
        path = f"/v3/historical-candle/{encoded}/{unit}/{interval}/{to_date}"
        if from_date:
            path += f"/{from_date}"
        return candles_to_frame(self.get(path))

    def intraday(self, instrument_key: str, unit: str = "minutes", interval: int = 1):
        encoded = requests.utils.quote(instrument_key, safe="")
        path = f"/v3/historical-candle/intraday/{encoded}/{unit}/{interval}"
        return candles_to_frame(self.get(path))
