from __future__ import annotations

import csv
import gzip
import io
import os
import re
import threading
import time
from typing import Any

import requests

NIFTY_BASE = "https://www.niftyindices.com"
NSE_BASE = "https://www.nseindia.com"
NSE_ALL_INDICES_URL = NSE_BASE + "/api/allIndices"
NSE_INDEX_MEMBERS_URL = NSE_BASE + "/api/equity-stockIndices"
UPSTOX_INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
UPSTOX_QUOTE_URL = "https://api.upstox.com/v3/market-quote/quotes"

# These are the sectoral indices used for the scanner's sector-strength context.
# NSE's current sectoral-index catalogue includes these sectors. We deliberately
# keep the universe to sectoral indices, not broad/thematic indices.
SECTOR_PAGES = {
    "NIFTY AUTO": "nifty-auto",
    "NIFTY BANK": "nifty-bank",
    "NIFTY FINANCIAL SERVICES": "nifty-financial-services",
    "NIFTY FMCG": "nifty-fmcg",
    "NIFTY IT": "nifty-it",
    "NIFTY PHARMA": "nifty-pharma",
    "NIFTY HEALTHCARE": "nifty-healthcare",
    "NIFTY METAL": "nifty-metal",
    "NIFTY REALTY": "nifty-realty",
    "NIFTY MEDIA": "nifty-media",
    "NIFTY CONSUMER DURABLES": "nifty-consumer-durables",
    "NIFTY OIL & GAS": "nifty-oil-and-gas",
    "NIFTY POWER": "nifty-power",
    "NIFTY PSU BANK": "nifty-psu-bank",
    "NIFTY PRIVATE BANK": "nifty-private-bank",
    "NIFTY TELECOMMUNICATION": "nifty-telecommunications",
    "NIFTY CHEMICALS": "nifty-chemicals",
    "NIFTY CONSTRUCTION": "nifty-construction",
    "NIFTY CAPITAL GOODS": "nifty-capital-goods",
    "NIFTY CONSUMER SERVICES": "nifty-consumer-services",
}

# Prefer a specific sectoral index when a stock belongs to multiple indices.
SECTOR_PRIORITY = [
    "NIFTY BANK",
    "NIFTY PRIVATE BANK",
    "NIFTY PSU BANK",
    "NIFTY AUTO",
    "NIFTY IT",
    "NIFTY PHARMA",
    "NIFTY HEALTHCARE",
    "NIFTY FMCG",
    "NIFTY METAL",
    "NIFTY REALTY",
    "NIFTY MEDIA",
    "NIFTY CONSUMER DURABLES",
    "NIFTY OIL & GAS",
    "NIFTY POWER",
    "NIFTY CHEMICALS",
    "NIFTY CAPITAL GOODS",
    "NIFTY CONSTRUCTION",
    "NIFTY TELECOMMUNICATION",
    "NIFTY CONSUMER SERVICES",
    "NIFTY FINANCIAL SERVICES",
]

ALIASES = {
    "NIFTY FIN SERVICE": "NIFTY FINANCIAL SERVICES",
    "NIFTY FINANCIAL SERVICES INDEX": "NIFTY FINANCIAL SERVICES",
    "NIFTY FINANCIAL SERVICES EX-BANK": "NIFTY FINANCIAL SERVICES",
    "NIFTY HEALTHCARE INDEX": "NIFTY HEALTHCARE",
    "NIFTY OIL AND GAS": "NIFTY OIL & GAS",
    "NIFTY OIL AND GAS INDEX": "NIFTY OIL & GAS",
    "NIFTY TELECOM": "NIFTY TELECOMMUNICATION",
    "NIFTY TELECOMMUNICATIONS": "NIFTY TELECOMMUNICATION",
    "NIFTY TELECOMMUNICATION INDEX": "NIFTY TELECOMMUNICATION",
    "NIFTY CAPITAL GOODS INDEX": "NIFTY CAPITAL GOODS",
    "NIFTY CONSUMER DURABLES INDEX": "NIFTY CONSUMER DURABLES",
    "NIFTY CONSUMER SERVICES INDEX": "NIFTY CONSUMER SERVICES",
    "NIFTY CONSTRUCTION INDEX": "NIFTY CONSTRUCTION",
    "NIFTY CHEMICALS INDEX": "NIFTY CHEMICALS",
    "NIFTY POWER INDEX": "NIFTY POWER",
    "NIFTY REALTY INDEX": "NIFTY REALTY",
    "NIFTY METAL INDEX": "NIFTY METAL",
    "NIFTY MEDIA INDEX": "NIFTY MEDIA",
    "NIFTY PHARMA INDEX": "NIFTY PHARMA",
    "NIFTY IT INDEX": "NIFTY IT",
    "NIFTY FMCG INDEX": "NIFTY FMCG",
    "NIFTY AUTO INDEX": "NIFTY AUTO",
    "NIFTY BANK INDEX": "NIFTY BANK",
    "NIFTY PSU BANK INDEX": "NIFTY PSU BANK",
    "NIFTY PRIVATE BANK INDEX": "NIFTY PRIVATE BANK",
}


def _norm(value: str) -> str:
    value = str(value or "").upper().replace("&", " AND ")
    value = re.sub(r"[^A-Z0-9]+", " ", value)
    return " ".join(value.split())


def _canonical(value: str) -> str | None:
    raw = str(value or "").strip().upper()
    if raw in SECTOR_PAGES:
        return raw
    if raw in ALIASES:
        return ALIASES[raw]
    normalized = _norm(raw)
    for sector in SECTOR_PAGES:
        if normalized == _norm(sector):
            return sector
    for alias, sector in ALIASES.items():
        if normalized == _norm(alias):
            return sector
    return None


class SectorRanker:
    """
    Sector context without NSE's browser-protected quote-equity endpoint.

    Sources:
      - NSE equity-stockIndices -> stock -> sector membership.
      - NSE allIndices -> live sector-index percentage change.
      - Upstox authenticated market quote -> fallback live sector-index data.

    The NSE quote-equity endpoint is intentionally not used because it can
    return HTTP 403 to ordinary server-side requests.
    """

    def __init__(self, refresh_seconds: int = 60):
        self.refresh_seconds = refresh_seconds
        self.membership_refresh_seconds = 6 * 60 * 60
        self._lock = threading.Lock()
        self._last = 0.0
        self._membership_last = 0.0
        self._sector_change: dict[str, float] = {}
        self._sector_display: dict[str, str] = {}
        self._sector_rank: dict[str, int] = {}
        self._symbol_sector: dict[str, str] = {}
        self._sector_keys: dict[str, str] = {}
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-IN,en;q=0.9",
            "Referer": NSE_BASE + "/",
            "Connection": "keep-alive",
        })
        self._load_upstox_sector_index_keys()
        self._refresh_membership(force=True)

    def _load_upstox_sector_index_keys(self) -> None:
        token = os.getenv("UPSTOX_ACCESS_TOKEN")
        if not token:
            print("[SECTOR] UPSTOX_ACCESS_TOKEN missing; sector quotes unavailable")
            return

        try:
            response = requests.get(UPSTOX_INSTRUMENTS_URL, timeout=30)
            response.raise_for_status()
            raw = gzip.GzipFile(fileobj=io.BytesIO(response.content)).read()
            rows = __import__("json").loads(raw)

            found: dict[str, str] = {}
            for row in rows:
                if row.get("segment") != "NSE_INDEX" or row.get("instrument_type") != "INDEX":
                    continue
                name = str(row.get("name") or row.get("trading_symbol") or "").strip()
                sector = _canonical(name)
                if sector and sector not in found:
                    found[sector] = str(row.get("instrument_key"))

            self._sector_keys = found
            print(f"[SECTOR] Upstox sector index keys: {len(found)}/{len(SECTOR_PAGES)}")
        except Exception as exc:
            print(f"[SECTOR] Upstox index master error: {exc}")

    def _refresh_membership(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._membership_last < self.membership_refresh_seconds:
            return

        with self._lock:
            now = time.time()
            if not force and now - self._membership_last < self.membership_refresh_seconds:
                return

            mapping: dict[str, str] = {}
            loaded = 0

            # NSE's equity-stockIndices endpoint returns the actual constituent
            # rows for an index. This avoids the separate niftyindices.com DNS
            # dependency that was failing in the worker.
            for sector in SECTOR_PRIORITY:
                try:
                    response = self._session.get(
                        NSE_INDEX_MEMBERS_URL,
                        params={"index": sector},
                        timeout=12,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    rows = payload.get("data") or []
                    if not rows:
                        print(f"[SECTOR] NSE returned 0 constituents: {sector}")
                        continue

                    count = 0
                    for row in rows:
                        symbol = row.get("symbol") or row.get("Symbol")
                        if symbol:
                            mapping.setdefault(str(symbol).strip().upper(), sector)
                            count += 1
                    if count:
                        loaded += 1
                except Exception as exc:
                    print(f"[SECTOR] NSE membership load failed {sector}: {exc}")

            # Fallback to Nifty Indices only if NSE could not provide anything.
            if not mapping:
                for sector in SECTOR_PRIORITY:
                    slug = SECTOR_PAGES[sector]
                    try:
                        page_url = f"{NIFTY_BASE}/indices/equity/sectoral-indices/{slug}"
                        page = self._session.get(page_url, timeout=12)
                        page.raise_for_status()
                        match = re.search(
                            r"https?://www\\.niftyindices\\.com//IndexConstituent/([^\"']+?\.csv)",
                            page.text,
                            flags=re.IGNORECASE,
                        )
                        if not match:
                            match = re.search(
                                r"/?IndexConstituent/([^\"']+?\.csv)",
                                page.text,
                                flags=re.IGNORECASE,
                            )
                        if not match:
                            continue
                        csv_url = f"{NIFTY_BASE}/IndexConstituent/{match.group(1)}"
                        csv_response = self._session.get(csv_url, timeout=12)
                        csv_response.raise_for_status()
                        text = csv_response.content.decode("utf-8-sig", errors="replace")
                        rows = list(csv.DictReader(io.StringIO(text)))
                        for row in rows:
                            symbol = (
                                row.get("Symbol") or row.get("symbol") or
                                row.get("SYMBOL") or row.get("Trading Symbol") or
                                row.get("TradingSymbol")
                            )
                            if symbol:
                                mapping.setdefault(str(symbol).strip().upper(), sector)
                        if rows:
                            loaded += 1
                    except Exception as exc:
                        print(f"[SECTOR] Nifty fallback failed {sector}: {exc}")

            self._symbol_sector = mapping
            self._membership_last = time.time()
            print(
                f"[SECTOR] membership map loaded: {len(mapping)} stocks "
                f"across {loaded}/{len(SECTOR_PRIORITY)} sector indices"
            )

    def _apply_ranked_changes(self, changes: dict[str, float]) -> None:
        if not changes:
            return
        ranked = sorted(changes.items(), key=lambda kv: kv[1], reverse=True)
        self._sector_change = changes
        self._sector_display = {name: name for name in changes}
        self._sector_rank = {name: index + 1 for index, (name, _) in enumerate(ranked)}
        print(
            f"[SECTOR] live refresh {len(changes)} indices; "
            f"top={ranked[:3]} bottom={ranked[-3:]}"
        )

    def _refresh_live_indices(self) -> None:
        # Primary source: NSE allIndices. It gives the sector index's current
        # percentage change directly, so no prev-close calculation is needed.
        try:
            response = self._session.get(NSE_ALL_INDICES_URL, timeout=10)
            response.raise_for_status()
            payload = response.json()
            changes: dict[str, float] = {}
            for row in payload.get("data") or []:
                name = str(row.get("index") or row.get("indexName") or "").strip()
                sector = _canonical(name)
                if not sector:
                    continue
                value = row.get("percentChange")
                if value is None:
                    value = row.get("percChange")
                if value is None:
                    continue
                changes[sector] = float(value)
            if changes:
                self._apply_ranked_changes(changes)
                return
        except Exception as exc:
            print(f"[SECTOR] NSE allIndices error: {exc}")

        # Fallback: Upstox authenticated index quotes.
        token = os.getenv("UPSTOX_ACCESS_TOKEN")
        if not token:
            return
        if not self._sector_keys:
            self._load_upstox_sector_index_keys()
        if not self._sector_keys:
            return

        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        try:
            response = requests.get(
                UPSTOX_QUOTE_URL,
                params={"instrument_key": ",".join(self._sector_keys.values())},
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            changes: dict[str, float] = {}
            by_key = {str(key).upper(): sector for sector, key in self._sector_keys.items()}

            for data_key, item in (payload.get("data") or {}).items():
                # Upstox keys are returned as EXCHANGE:SYMBOL while instrument
                # files use EXCHANGE|SYMBOL.
                normalized = str(data_key).replace(":", "|", 1).upper()
                sector = by_key.get(normalized)
                if not sector:
                    continue

                net_change = item.get("net_change")
                prev_close = item.get("prev_close_price")
                last_price = item.get("last_price")

                if net_change is not None and prev_close not in (None, 0):
                    changes[sector] = float(net_change) / float(prev_close) * 100.0
                elif last_price is not None and prev_close not in (None, 0):
                    changes[sector] = (
                        (float(last_price) - float(prev_close)) /
                        float(prev_close) * 100.0
                    )

            if changes:
                self._apply_ranked_changes(changes)
            else:
                print("[SECTOR] Upstox returned 0 usable sector index quotes")
        except Exception as exc:
            print(f"[SECTOR] Upstox live quote error: {exc}")

    def refresh(self) -> None:
        self._refresh_membership()
        now = time.time()
        if now - self._last < self.refresh_seconds:
            return

        with self._lock:
            now = time.time()
            if now - self._last < self.refresh_seconds:
                return
            self._refresh_live_indices()
            self._last = time.time()

    def get(self, symbol: str, direction: str) -> dict[str, Any]:
        self.refresh()

        sector = self._symbol_sector.get(str(symbol or "").strip().upper())
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
            "sector": self._sector_display.get(sector, sector),
            "sector_change": change,
            "sector_rank": rank,
            "sector_rank_type": rank_type,
            "sector_bonus": bonus,
        }
