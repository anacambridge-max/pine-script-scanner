"""NSE pre-market study for 09:00–09:08 IST.

Uses NSE's public market-data endpoints behind a cookie-backed session.
This module is deliberately separate from the confirmed BUY/SELL engine.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time as time_module
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1

IST = ZoneInfo("Asia/Kolkata")
WINDOW_START = time(9, 0)
WINDOW_END = time(9, 8)
NSE_HOME = "https://www.nseindia.com/"
PREOPEN_API = "https://www.nseindia.com/api/market-data-pre-open?key=ALL"
OI_SPURTS_API = "https://www.nseindia.com/api/live-analysis-oi-spurts-underlyings?type=underlying"
PREOPEN_PAGE = "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market"
OI_PAGE = "https://www.nseindia.com/market-data/oi-spurts"


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "").replace("₹", "")
    if not text or text in {"-", "--", "NA", "N/A"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _pick(obj: dict[str, Any], *keys: str) -> Any:
    lowered = {str(k).casefold().replace("_", "").replace(" ", ""): v for k, v in obj.items()}
    for key in keys:
        k = key.casefold().replace("_", "").replace(" ", "")
        if k in lowered:
            return lowered[k]
    return None


def _nse_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/129 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": NSE_HOME,
        "Connection": "keep-alive",
    })
    # NSE commonly expects cookies from the home page before API calls.
    response = session.get(NSE_HOME, timeout=12)
    response.raise_for_status()
    return session


def _get_json(session: requests.Session, url: str) -> dict[str, Any] | list[Any]:
    response = session.get(url, timeout=12, headers={"Referer": PREOPEN_PAGE if "pre-open" in url else OI_PAGE})
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, (dict, list)):
        raise ValueError(f"Unexpected NSE payload at {url}")
    return payload


def _is_retryable_nse_error(exc: Exception) -> bool:
    if isinstance(exc, requests.Timeout):
        return True
    if isinstance(exc, requests.HTTPError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return status in {401, 403}
    return False


def _fetch_payloads_with_retry() -> tuple[dict[str, Any] | list[Any], dict[str, Any] | list[Any]]:
    """Fetch pre-open and OI independently so one NSE endpoint cannot suppress the other.

    A fresh cookie-backed session is warmed for each attempt. Transient 401/403
    and timeout errors are retried up to three times. If one source remains
    unavailable but the other works, return the usable source and let the caller
    persist a partial snapshot instead of discarding all market context.
    """
    last_error: Exception | None = None
    latest_preopen: dict[str, Any] | list[Any] = {}
    latest_oi: dict[str, Any] | list[Any] = {}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            session = _nse_session()
        except Exception as exc:
            last_error = exc
            retryable = _is_retryable_nse_error(exc)
            if not retryable or attempt >= MAX_ATTEMPTS:
                logger.warning(
                    "[NSE PRE-MARKET] session warmup failed after attempt %s/%s: %s: %s",
                    attempt, MAX_ATTEMPTS, type(exc).__name__, exc,
                )
                break
            delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning("[NSE PRE-MARKET] session warmup retry %s/%s in %ss", attempt, MAX_ATTEMPTS, delay)
            time_module.sleep(delay)
            continue

        errors: list[Exception] = []
        for label, url in (("pre-open", PREOPEN_API), ("OI-spurts", OI_SPURTS_API)):
            try:
                payload = _get_json(session, url)
                if label == "pre-open":
                    latest_preopen = payload
                else:
                    latest_oi = payload
            except Exception as exc:
                last_error = exc
                errors.append(exc)
                logger.warning(
                    "[NSE PRE-MARKET] %s source failed on attempt %s/%s: %s: %s",
                    label, attempt, MAX_ATTEMPTS, type(exc).__name__, exc,
                )

        # A complete response is ideal; a partial response is still useful
        # and is preferable to losing both sources because one endpoint failed.
        if attempt >= MAX_ATTEMPTS and not latest_preopen and not latest_oi:
            logger.warning(
                "[NSE PRE-MARKET] graceful skip after attempt %s/%s; both sources unavailable",
                attempt, MAX_ATTEMPTS,
            )
        if latest_preopen and latest_oi:
            return latest_preopen, latest_oi
        if latest_preopen or latest_oi:
            retryable_errors = [exc for exc in errors if _is_retryable_nse_error(exc)]
            if not retryable_errors or attempt >= MAX_ATTEMPTS:
                return latest_preopen, latest_oi
        elif errors and any(not _is_retryable_nse_error(exc) for exc in errors):
            # Both sources are unusable for a non-retryable reason.
            break

        if attempt < MAX_ATTEMPTS:
            delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "[NSE PRE-MARKET] retry %s/%s after endpoint failure; fresh session in %ss",
                attempt, MAX_ATTEMPTS - 1, delay,
            )
            time_module.sleep(delay)

    if latest_preopen or latest_oi:
        return latest_preopen, latest_oi
    if last_error is not None:
        raise last_error
    raise RuntimeError("NSE pre-open and OI-spurts endpoints returned no usable payloads")


def _rows(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    for key in ("data", "records", "rows", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            nested = _rows(value)
            if nested:
                return nested
    return []


def _flatten_preopen(row: dict[str, Any]) -> dict[str, Any]:
    # NSE payloads nest fields differently across page/API versions. Flatten
    # nested dicts recursively, while retaining scalar fields from the parent.
    merged: dict[str, Any] = {}

    def visit(value: Any) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            if isinstance(child, dict):
                visit(child)
            elif not isinstance(child, list):
                # Prefer the first non-empty value for duplicate field names;
                # top-level metadata should not be overwritten by blank nested values.
                if key not in merged or merged[key] in (None, "", "-", "--"):
                    merged[key] = child

    visit(row)
    symbol = _pick(merged, "symbol", "identifier", "tradingSymbol", "security")
    prev_close = _number(_pick(merged, "previousClose", "prevClose", "previous_close", "closePrice", "prvClose"))
    iep = _number(_pick(merged, "iep", "indicativeEquilibriumPrice", "indicativePrice", "finalPrice", "equilibriumPrice"))
    tradable_qty = _number(_pick(merged, "finalQuantity", "totalTradedQuantity", "quantityTraded", "finalVolume", "indicativeTradableQuantity", "totalTradedVolume"))
    buy_qty = _number(_pick(merged, "totalBuyQuantity", "buyQuantity", "totalBuyQty", "atoBuyQty", "atpBuyQty"))
    sell_qty = _number(_pick(merged, "totalSellQuantity", "sellQuantity", "totalSellQty", "atoSellQty", "atpSellQty"))
    imbalance = _number(_pick(merged, "imbalanceQuantity", "indicativeImbalanceQuantity", "imbalanceQty", "marketImbalance"))
    reported_change = _number(_pick(merged, "pChange", "changePercent", "percentChange"))
    gap_pct = reported_change
    if gap_pct is None and iep is not None and prev_close:
        gap_pct = round((iep / prev_close - 1) * 100, 4)
    if imbalance is None and buy_qty is not None and sell_qty is not None:
        imbalance = buy_qty - sell_qty
    return {
        "symbol": str(symbol or "").strip().upper(),
        "previous_close": prev_close,
        "indicative_price": iep,
        "indicative_gap_pct": gap_pct,
        "indicative_tradable_qty": tradable_qty,
        "buy_qty": buy_qty,
        "sell_qty": sell_qty,
        "imbalance_qty": imbalance,
        "raw": merged,
    }


def _flatten_oi(row: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}

    def visit(value: Any) -> None:
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            if isinstance(child, dict):
                visit(child)
            elif not isinstance(child, list):
                if key not in merged or merged[key] in (None, "", "-", "--"):
                    merged[key] = child

    visit(row)
    symbol = _pick(merged, "symbol", "underlying", "underlyingSymbol", "identifier")
    # NSE's OI-spurts payload commonly uses pchangeInOI. Do not use generic
    # pChange: that can mean underlying-price change rather than OI change.
    oi_change_pct = _number(_pick(
        merged, "pchangeInOI", "pChangeInOI", "oiChangePercent",
        "changeInOIPercent", "percentChangeInOI", "percentChangeOI",
    ))
    # Some endpoint versions expose current/previous OI but omit the percentage.
    # Derive it only when both contract counts are available and previous OI > 0.
    if oi_change_pct is None:
        current_oi = _number(_pick(merged, "latestOI", "currentOI", "openInterest", "oi"))
        previous_oi = _number(_pick(merged, "prevOI", "previousOI", "previousOpenInterest", "prevOpenInterest"))
        if current_oi is not None and previous_oi is not None and previous_oi > 0:
            oi_change_pct = round((current_oi / previous_oi - 1.0) * 100.0, 4)
    volume = _number(_pick(merged, "volume", "totalTradedVolume", "tradedVolume"))
    return {"symbol": str(symbol or "").strip().upper(), "oi_change_pct": oi_change_pct,
            "oi_volume": volume, "raw": merged}


def _score_preopen(row: dict[str, Any]) -> tuple[int, str, list[str]]:
    gap = row.get("indicative_gap_pct")
    imbalance = row.get("imbalance_qty")
    buy_qty, sell_qty = row.get("buy_qty"), row.get("sell_qty")
    tradable = row.get("indicative_tradable_qty")
    score = 0
    reasons: list[str] = []
    if gap is not None:
        if gap >= 2:
            score += 30; reasons.append(f"strong positive indicative gap {gap:.2f}%")
        elif gap >= 0.75:
            score += 20; reasons.append(f"positive indicative gap {gap:.2f}%")
        elif gap <= -2:
            score -= 30; reasons.append(f"strong negative indicative gap {gap:.2f}%")
        elif gap <= -0.75:
            score -= 20; reasons.append(f"negative indicative gap {gap:.2f}%")
        else:
            reasons.append(f"small indicative gap {gap:+.2f}%")
    if buy_qty is not None and sell_qty is not None and buy_qty + sell_qty > 0:
        buy_share = buy_qty / (buy_qty + sell_qty)
        if buy_share >= 0.65:
            score += 20; reasons.append("buy quantity dominates sell quantity")
        elif buy_share <= 0.35:
            score -= 20; reasons.append("sell quantity dominates buy quantity")
    elif imbalance is not None and tradable and tradable > 0:
        ratio = imbalance / tradable
        if ratio >= 0.25:
            score += 15; reasons.append("positive order imbalance")
        elif ratio <= -0.25:
            score -= 15; reasons.append("negative order imbalance")
    direction = "BULLISH BIAS" if score >= 15 else "BEARISH BIAS" if score <= -15 else "NEUTRAL / MIXED"
    return score, direction, reasons


class NSEPreMarketStudy:
    """Collect snapshots from 09:00 to 09:08 IST and retain a daily audit trail."""
    def __init__(self, db_path: str | Path = "data/nse_premarket.sqlite3"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_time TEXT NOT NULL, symbol TEXT NOT NULL, source TEXT NOT NULL,
                payload_json TEXT NOT NULL, PRIMARY KEY(snapshot_time, symbol, source))""")
            db.execute("CREATE INDEX IF NOT EXISTS snapshots_symbol_time_idx ON snapshots(symbol, snapshot_time)")

    def collect(self, now: datetime | None = None, allowed_symbols: set[str] | None = None) -> dict[str, Any]:
        now = now or datetime.now(IST)
        if now.tzinfo is None:
            return {"status": "invalid_time", "snapshot_time": now.isoformat(), "rows": []}
        now = now.astimezone(IST)
        try:
            from worker.hot_stocks_config import NSE_HOLIDAYS
        except Exception:
            NSE_HOLIDAYS = set()
        if (now.weekday() >= 5 or now.date().isoformat() in NSE_HOLIDAYS
                or not (WINDOW_START <= now.time().replace(tzinfo=None) <= WINDOW_END)):
            return {"status": "outside_window", "snapshot_time": now.isoformat(), "rows": []}
        try:
            preopen_payload, oi_payload = _fetch_payloads_with_retry()
        except Exception as exc:
            # A failed exchange fetch must remain retryable in the next minute.
            return {"status": "unavailable", "snapshot_time": now.isoformat(),
                    "rows": [], "error": f"{type(exc).__name__}: {exc}"}
        preopen_rows = [_flatten_preopen(x) for x in _rows(preopen_payload)]
        oi_rows = [_flatten_oi(x) for x in _rows(oi_payload)]
        if allowed_symbols is not None:
            # Keep the study aligned with the scanner's F&O stock universe.
            allowed = {str(symbol).strip().upper() for symbol in allowed_symbols}
            preopen_rows = [row for row in preopen_rows if row.get("symbol") in allowed]
            oi_rows = [row for row in oi_rows if row.get("symbol") in allowed]
        oi_by_symbol: dict[str, dict[str, Any]] = {}
        for item in oi_rows:
            if item["symbol"]:
                oi_by_symbol[item["symbol"]] = item
        # Keep the union of both official sources. An OI-spurt symbol must not
        # disappear merely because it has no row in the pre-open payload.
        preopen_by_symbol = {
            row["symbol"]: row for row in preopen_rows if row.get("symbol")
        }
        symbols = sorted(set(preopen_by_symbol) | set(oi_by_symbol))
        merged_rows = []
        stamp = now.replace(second=0, microsecond=0).isoformat()
        with sqlite3.connect(self.db_path) as db:
            for symbol in symbols:
                item = preopen_by_symbol.get(symbol, {})
                oi = oi_by_symbol.get(symbol, {})
                score, direction, reasons = _score_preopen(item)
                if not item:
                    reasons.append("OI-spurt symbol; pre-open fields unavailable")
                oi_change = oi.get("oi_change_pct")
                # OI change is context, not directional proof; show it separately.
                if oi_change is not None and abs(float(oi_change)) >= 5:
                    reasons.append(f"OI spurt {float(oi_change):+.2f}% (context only)")
                item_out = {
                    "snapshot_time": stamp, "symbol": symbol,
                    "previous_close": item.get("previous_close"),
                    "indicative_price": item.get("indicative_price"),
                    "indicative_gap_pct": item.get("indicative_gap_pct"),
                    "indicative_tradable_qty": item.get("indicative_tradable_qty"),
                    "buy_qty": item.get("buy_qty"), "sell_qty": item.get("sell_qty"),
                    "imbalance_qty": item.get("imbalance_qty"),
                    "oi_change_pct": oi_change, "oi_volume": oi.get("oi_volume"),
                    "preopen_score": score, "preopen_bias": direction, "reasons": reasons,
                    "source_preopen": PREOPEN_PAGE if item else None,
                    "source_oi": OI_PAGE if oi else None,
                }
                merged_rows.append(item_out)
                if item:
                    db.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?)",
                               (stamp, symbol, "preopen", json.dumps(item.get("raw", {}), ensure_ascii=False, default=str)))
                if oi:
                    db.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?)",
                               (stamp, symbol, "oi_spurts", json.dumps(oi.get("raw", {}), ensure_ascii=False, default=str)))
        merged_rows.sort(
            key=lambda x: (abs(x["preopen_score"]), abs(x.get("oi_change_pct") or 0),
                           abs(x.get("indicative_gap_pct") or 0)),
            reverse=True,
        )
        if not merged_rows:
            return {"status": "empty", "snapshot_time": stamp, "rows": [],
                    "preopen_count": len(preopen_rows), "oi_count": len(oi_rows)}
        return {"status": "ok", "snapshot_time": stamp, "rows": merged_rows[:200],
                "preopen_count": len(preopen_rows), "oi_count": len(oi_rows)}

    def latest(self, limit: int = 30) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as db:
            rows = db.execute("""SELECT snapshot_time,symbol,source,payload_json FROM snapshots
                ORDER BY snapshot_time DESC LIMIT ?""", (limit * 2,)).fetchall()
        return [{"snapshot_time": r[0], "symbol": r[1], "source": r[2],
                 "payload": json.loads(r[3])} for r in rows]
