from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any
import requests

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
            "Authorization": f"Bearer {self.access_token}",
        }

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        r = requests.get(self.base_url + path, headers=self.headers, params=params, timeout=20)
        r.raise_for_status()
        return r.json()
