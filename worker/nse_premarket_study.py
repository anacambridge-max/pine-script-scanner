"""NSE pre-market study helpers for the 09:00–09:08 IST window.

Sources:
- https://www.nseindia.com/market-data/oi-spurts
- https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market

The NSE website's underlying API schema can change and may reject automated clients.
This module fails closed: it records source status and never fabricates missing values.
It is deliberately separate from the confirmed BUY/SELL signal engine.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, time as daytime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

IST = ZoneInfo("Asia/Kolkata")
START = daytime(9, 0)
END = daytime(9, 8)
OI_URL = "https://www.nseindia.com/market-data/oi-spurts"
PREOPEN_URL = "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market"
DEFAULT_OUT = Path(os.getenv("NSE_PREMARKET_OUT", "data/nse_premarket"))


@dataclass
class StudyRow:
    snapshot_time: str
    symbol: str
    source: str
    previous_close: float | None = None
    indicative_price: float | None = None
    indicative_gap_pct: float | None = None
    indicative_imbalance_qty: float | None = None
    oi_change_pct: float | None = None
    oi_change: float | None = None
    volume: float | None = None
    interpretation: str = ""
    raw: dict[str, Any] | None = None


def in_study_window(now: datetime | None = None) -> bool:
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        return False
    local = now.astimezone(IST)
    return local.weekday() < 5 and START <= local.time().replace(tzinfo=None) <= END


def _number(value: Any) -> float | None:
    if value is None:
        return None
    text = re.sub(r"[,₹%\s]", "", str(value)).replace("—", "").replace("-", "")
    if not text or text.casefold() in {"na", "n/a", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-IN,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    })
    # Prime cookies using the official public page before calling the page URL.
    session.get("https://www.nseindia.com/", timeout=12)
    return session


def _get_html(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=15)
    response.raise_for_status()
    return response.text


def _parse_preopen_html(raw: str, snapshot: str) -> list[StudyRow]:
    """Parse rendered table rows when NSE returns a populated HTML table."""
    try:
        import pandas as pd
        tables = pd.read_html(raw)
    except Exception:
        return []
    output: list[StudyRow] = []
    for table in tables:
        if table.empty:
            continue
        columns = {re.sub(r"[^a-z0-9]", "", str(c).casefold()): c for c in table.columns}
        symbol_col = next((columns[k] for k in columns if "symbol" in k), None)
        if symbol_col is None:
            continue
        def col(*hints: str):
            return next((columns[k] for k in columns if any(h in k for h in hints)), None)
        prev_col = col("prevclose", "previousclose")
        iep_col = col("iep", "indicativeequilibriumprice")
        imbalance_col = col("indicativeimbalancequantity", "imbalanceqty")
        for _, item in table.iterrows():
            symbol = str(item.get(symbol_col, "")).strip().upper()
            if not symbol or symbol in {"TOTAL", "NAN", "-"}:
                continue
            previous = _number(item.get(prev_col)) if prev_col else None
            indicative = _number(item.get(iep_col)) if iep_col else None
            gap = ((indicative - previous) / previous * 100) if previous and indicative is not None else None
            output.append(StudyRow(
                snapshot_time=snapshot, symbol=symbol, source="NSE_PREOPEN",
                previous_close=previous, indicative_price=indicative,
                indicative_gap_pct=round(gap, 3) if gap is not None else None,
                indicative_imbalance_qty=_number(item.get(imbalance_col)) if imbalance_col else None,
                raw={str(k): str(v) for k, v in item.to_dict().items()},
            ))
    # Keep first row for a symbol if multiple NSE tables repeat it.
    dedup: dict[str, StudyRow] = {}
    for row in output:
        dedup.setdefault(row.symbol, row)
    return list(dedup.values())


def _parse_oi_html(raw: str, snapshot: str) -> list[StudyRow]:
    """Best-effort parser for NSE's visible Change in Open Interest tables."""
    try:
        import pandas as pd
        tables = pd.read_html(raw)
    except Exception:
        return []
    output: list[StudyRow] = []
    for table in tables:
        if table.empty:
            continue
        columns = {re.sub(r"[^a-z0-9]", "", str(c).casefold()): c for c in table.columns}
        symbol_col = next((columns[k] for k in columns if "symbol" in k or "underlying" in k), None)
        if symbol_col is None:
            continue
        oi_col = next((columns[k] for k in columns if "changeinoi" in k or "oichange" in k), None)
        pct_col = next((columns[k] for k in columns if "changeinoi" in k and "percent" in k or "oichangepercent" in k), None)
        volume_col = next((columns[k] for k in columns if "volume" in k), None)
        for _, item in table.iterrows():
            symbol = str(item.get(symbol_col, "")).strip().upper()
            if not symbol or symbol in {"TOTAL", "NAN", "-"}:
                continue
            output.append(StudyRow(
                snapshot_time=snapshot, symbol=symbol, source="NSE_OI_SPURTS",
                oi_change=_number(item.get(oi_col)) if oi_col else None,
                oi_change_pct=_number(item.get(pct_col)) if pct_col else None,
                volume=_number(item.get(volume_col)) if volume_col else None,
                raw={str(k): str(v) for k, v in item.to_dict().items()},
            ))
    return output


def collect_snapshot(session: requests.Session | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(IST)
    snapshot = now.isoformat(timespec="seconds")
    session = session or _session()
    result: dict[str, Any] = {
        "snapshot_time": snapshot,
        "window": "09:00-09:08 IST",
        "sources": {
            "nse_preopen": {"url": PREOPEN_URL, "status": "not_fetched", "rows": []},
            "nse_oi_spurts": {"url": OI_URL, "status": "not_fetched", "rows": []},
        },
    }
    for key, url, parser in (
        ("nse_preopen", PREOPEN_URL, _parse_preopen_html),
        ("nse_oi_spurts", OI_URL, _parse_oi_html),
    ):
        try:
            raw = _get_html(session, url)
            rows = parser(raw, snapshot)
            result["sources"][key]["status"] = "ok" if rows else "no_parseable_rows"
            result["sources"][key]["rows"] = [asdict(row) for row in rows]
        except Exception as exc:
            result["sources"][key]["status"] = "error"
            result["sources"][key]["error"] = f"{type(exc).__name__}: {exc}"
    return result


def save_snapshot(payload: dict[str, Any], output_dir: Path = DEFAULT_OUT) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(payload["snapshot_time"]).astimezone(IST)
    path = output_dir / f"nse_premarket_{stamp:%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_study_window() -> list[Path]:
    """Sample once per minute from 09:00 through 09:08 IST on weekdays."""
    paths: list[Path] = []
    last_minute = None
    while True:
        now = datetime.now(IST)
        if now.weekday() >= 5 or now.time() > END:
            break
        if now.time() < START:
            time.sleep(1)
            continue
        minute = now.strftime("%Y%m%d%H%M")
        if minute != last_minute:
            try:
                payload = collect_snapshot(now=now)
                paths.append(save_snapshot(payload))
                print("[NSE PREMARKET]", now.strftime("%H:%M:%S"), {
                    key: value["status"] for key, value in payload["sources"].items()
                })
            except Exception as exc:
                print(f"[NSE PREMARKET ERROR] {type(exc).__name__}: {exc}")
            last_minute = minute
        time.sleep(max(1, 60 - datetime.now(IST).second))
    return paths


def export_csv(json_path: Path, csv_path: Path | None = None) -> Path:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    csv_path = csv_path or json_path.with_suffix(".csv")
    rows = []
    for source in payload.get("sources", {}).values():
        rows.extend(source.get("rows", []))
    keys = sorted({key for row in rows for key in row})
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    return csv_path


if __name__ == "__main__":
    run_study_window()
