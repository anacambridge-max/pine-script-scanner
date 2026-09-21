from __future__ import annotations

import threading
import time
from typing import Any

import requests

NSE_BASE = "https://www.nseindia.com"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

# Primary NSE sectoral indices. A stock can belong to more than one NSE
# sectoral index; the first matching index below is used as its primary
# scanner sector so the scoring remains deterministic.
SECTOR_INDEXES = [
    "NIFTY AUTO", "NIFTY BANK", "NIFTY FINANCIAL SERVICES",
    "NIFTY FINANCIAL SERVICES EX-BANK", "NIFTY FMCG", "NIFTY IT",
    "NIFTY PHARMA", "NIFTY HEALTHCARE", "NIFTY METAL", "NIFTY REALTY",
    "NIFTY MEDIA", "NIFTY CONSUMER DURABLES", "NIFTY OIL & GAS",
    "NIFTY POWER", "NIFTY PSU BANK", "NIFTY PRIVATE BANK",
    "NIFTY TELECOMMUNICATION", "NIFTY CHEMICALS", "NIFTY CONSTRUCTION",
    "NIFTY CAPITAL MARKETS", "NIFTY CONSUMER SERVICES",
]

class SectorRanker:
    def __init__(self, refresh_seconds: int = 120):
        self.refresh_seconds = refresh_seconds
        self._lock = threading.Lock()
        self._last = 0.0
        self._stock_sector: dict[str, str] = {}
        self._sector_change: dict[str, float] = {}
        self._sector_rank: dict[str, int] = {}
        self._session = requests.Session()
        self._session.headers.update(NSE_HEADERS)

    def _get(self, path: str) -> dict[str, Any]:
        r = self._session.get(NSE_BASE + path, timeout=8)
        if r.status_code in (401, 403):
            # Warm the NSE session once and retry.
            try:
                self._session.get(NSE_BASE, timeout=5)
            except Exception:
                pass
            r = self._session.get(NSE_BASE + path, timeout=8)
        r.raise_for_status()
        return r.json()

    def refresh(self) -> None:
        now = time.time()
        if now - self._last < self.refresh_seconds:
            return
        with self._lock:
            now = time.time()
            if now - self._last < self.refresh_seconds:
                return

            stock_sector: dict[str, str] = {}
            for sector in SECTOR_INDEXES:
                try:
                    payload = self._get("/api/equity-stockIndices?index=" + sector.replace(" ", "%20").replace("&", "%26"))
                    for item in payload.get("data", []):
                        symbol = item.get("symbol")
                        if symbol and symbol not in stock_sector:
                            stock_sector[str(symbol)] = sector
                except Exception as exc:
                    print(f"[SECTOR] {sector}: {exc}")

            try:
                all_indices = self._get("/api/allIndices").get("data", [])
                changes = {}
                for item in all_indices:
                    name = str(item.get("indexName") or "")
                    if name in SECTOR_INDEXES:
                        value = item.get("percentChange", item.get("percChange"))
                        if value is not None:
                            changes[name] = float(value)
                ranked = sorted(changes.items(), key=lambda kv: kv[1], reverse=True)
                ranks = {name: i + 1 for i, (name, _) in enumerate(ranked)}
            except Exception as exc:
                print(f"[SECTOR] allIndices: {exc}")
                changes, ranks = {}, {}

            self._stock_sector = stock_sector
            self._sector_change = changes
            self._sector_rank = ranks
            self._last = time.time()

    def get(self, symbol: str, direction: str) -> dict[str, Any]:
        self.refresh()
        sector = self._stock_sector.get(symbol)
        change = self._sector_change.get(sector) if sector else None
        rank = self._sector_rank.get(sector) if sector else None

        bonus = 0
        rank_type = None
        if rank is not None and rank <= 3:
            if direction == "BUY" and change is not None and change > 0:
                bonus = 10
                rank_type = "TOP 3 GAINER"
            elif direction == "SELL" and change is not None and change < 0:
                bonus = 10
                rank_type = "TOP 3 LOSER"

        return {
            "sector": sector,
            "sector_change": change,
            "sector_rank": rank,
            "sector_rank_type": rank_type,
            "sector_bonus": bonus,
        }
