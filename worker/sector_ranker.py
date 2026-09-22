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

# NSE sectoral/thematic indices that are used for the scanner's
# "top 3 gainer / top 3 loser" context. The actual live index list comes
# from NSE /api/allIndices; these names are used for normalization and
# matching a stock's sector membership.
SECTOR_ALIASES = {
    "NIFTY AUTO": "NIFTY AUTO",
    "NIFTY BANK": "NIFTY BANK",
    "NIFTY FINANCIAL SERVICES": "NIFTY FINANCIAL SERVICES",
    "NIFTY FIN SERVICE": "NIFTY FINANCIAL SERVICES",
    "NIFTY FINANCIAL SERVICES EX-BANK": "NIFTY FINANCIAL SERVICES EX-BANK",
    "NIFTY FIN SERVICE EX-BANK": "NIFTY FINANCIAL SERVICES EX-BANK",
    "NIFTY FMCG": "NIFTY FMCG",
    "NIFTY IT": "NIFTY IT",
    "NIFTY PHARMA": "NIFTY PHARMA",
    "NIFTY HEALTHCARE": "NIFTY HEALTHCARE",
    "NIFTY HEALTHCARE INDEX": "NIFTY HEALTHCARE",
    "NIFTY METAL": "NIFTY METAL",
    "NIFTY REALTY": "NIFTY REALTY",
    "NIFTY MEDIA": "NIFTY MEDIA",
    "NIFTY CONSUMER DURABLES": "NIFTY CONSUMER DURABLES",
    "NIFTY OIL & GAS": "NIFTY OIL & GAS",
    "NIFTY OIL AND GAS": "NIFTY OIL & GAS",
    "NIFTY POWER": "NIFTY POWER",
    "NIFTY PSU BANK": "NIFTY PSU BANK",
    "NIFTY PRIVATE BANK": "NIFTY PRIVATE BANK",
    "NIFTY TELECOMMUNICATION": "NIFTY TELECOMMUNICATION",
    "NIFTY TELECOM": "NIFTY TELECOMMUNICATION",
    "NIFTY CHEMICALS": "NIFTY CHEMICALS",
    "NIFTY CONSTRUCTION": "NIFTY CONSTRUCTION",
    "NIFTY CAPITAL MARKETS": "NIFTY CAPITAL MARKETS",
    "NIFTY CONSUMER SERVICES": "NIFTY CONSUMER SERVICES",
}

def _norm(value: str) -> str:
    return " ".join(str(value or "").upper().replace("&", " AND ").split())


class SectorRanker:
    """
    Live sector context for confirmed scanner signals.

    Instead of downloading every sector's constituents, we:
      1. fetch NSE's live all-indices table once per refresh;
      2. fetch the confirmed stock's NSE quote to get its sector/index
         membership;
      3. match that sector to the live index change and rank all supported
         sector indices.

    This is much lighter and more reliable than 20+ sequential
    equity-stockIndices calls for every confirmed signal.
    """

    def __init__(self, refresh_seconds: int = 60):
        self.refresh_seconds = refresh_seconds
        self._lock = threading.Lock()
        self._last = 0.0
        self._sector_change: dict[str, float] = {}
        self._sector_display: dict[str, str] = {}
        self._sector_rank: dict[str, int] = {}
        self._session = requests.Session()
        self._session.headers.update(NSE_HEADERS)
        self._warm_session()

    def _warm_session(self) -> None:
        try:
            self._session.get(
                NSE_BASE,
                headers={
                    **NSE_HEADERS,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Referer": "",
                },
                timeout=8,
            )
        except Exception as exc:
            print(f"[SECTOR] NSE session warm-up: {exc}")

    def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        url = NSE_BASE + path
        response = self._session.get(url, params=params, timeout=8)
        if response.status_code in (401, 403):
            self._warm_session()
            response = self._session.get(url, params=params, timeout=8)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _candidate_sectors(payload: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        metadata = payload.get("metadata") or {}
        industry = payload.get("industryInfo") or {}

        for value in (
            metadata.get("pdSectorInd"),
            industry.get("sector"),
        ):
            if value:
                candidates.append(str(value).strip())

        all_memberships = metadata.get("pdSectorIndAll")
        if isinstance(all_memberships, list):
            candidates.extend(str(x).strip() for x in all_memberships if x)

        # Keep order, remove duplicates.
        return list(dict.fromkeys(candidates))

    def _resolve_sector(self, candidates: list[str]) -> tuple[str | None, str | None]:
        # First prefer an exact/alias match against the live NSE index names.
        for candidate in candidates:
            canonical = SECTOR_ALIASES.get(_norm(candidate))
            if canonical and canonical in self._sector_change:
                return canonical, self._sector_display.get(canonical, canonical)

        # Fallback: match the stock's NSE industry/sector wording to a
        # sectoral index name when NSE returns a slightly different label.
        for candidate in candidates:
            norm = _norm(candidate)
            for canonical in self._sector_change:
                if norm == _norm(canonical):
                    return canonical, self._sector_display.get(canonical, canonical)

        return None, None

    def refresh(self) -> None:
        now = time.time()
        if now - self._last < self.refresh_seconds:
            return

        with self._lock:
            now = time.time()
            if now - self._last < self.refresh_seconds:
                return

            payload = self._get_json("/api/allIndices")
            changes: dict[str, float] = {}
            display: dict[str, str] = {}

            for item in payload.get("data", []):
                name = str(item.get("indexName") or "").strip()
                if not name:
                    continue

                canonical = SECTOR_ALIASES.get(_norm(name))
                if not canonical:
                    continue

                value = item.get("percentChange", item.get("percChange"))
                if value is None:
                    continue

                try:
                    changes[canonical] = float(value)
                    display[canonical] = name
                except (TypeError, ValueError):
                    continue

            ranked = sorted(changes.items(), key=lambda kv: kv[1], reverse=True)
            self._sector_change = changes
            self._sector_display = display
            self._sector_rank = {name: i + 1 for i, (name, _) in enumerate(ranked)}
            self._last = time.time()

            print(
                f"[SECTOR] refreshed {len(changes)} sector indices; "
                f"top={ranked[:3]} bottom={ranked[-3:] if ranked else []}"
            )

    def get(self, symbol: str, direction: str) -> dict[str, Any]:
        self.refresh()

        quote = self._get_json("/api/quote-equity", params={"symbol": symbol})
        candidates = self._candidate_sectors(quote)
        sector, display_sector = self._resolve_sector(candidates)

        change = self._sector_change.get(sector) if sector else None
        rank = self._sector_rank.get(sector) if sector else None

        bonus = 0
        rank_type = None
        if rank is not None and rank <= 3 and change is not None:
            if direction == "BUY" and change > 0:
                bonus = 10
                rank_type = "TOP 3 GAINER"
            elif direction == "SELL" and change < 0:
                bonus = 10
                rank_type = "TOP 3 LOSER"

        return {
            "sector": display_sector or sector,
            "sector_change": change,
            "sector_rank": rank,
            "sector_rank_type": rank_type,
            "sector_bonus": bonus,
        }
