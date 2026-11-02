"""Timestamped NSE corporate filings as context, never as trade confirmation."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

from worker.hot_stocks_config import NSE_HOLIDAYS

IST = ZoneInfo("Asia/Kolkata")
NSE_URL = "https://www.nseindia.com/api/corporate-announcements"
MATERIAL_DESCRIPTIONS = (
    "financial results", "outcome of board meeting", "press release",
    "investor presentation", "order", "contract", "acquisition",
    "merger", "demerger", "buyback", "dividend", "fund raise",
)


def previous_trading_day(day):
    candidate = day - timedelta(days=1)
    while candidate.weekday() >= 5 or candidate.isoformat() in NSE_HOLIDAYS:
        candidate -= timedelta(days=1)
    return candidate


def select_filings(records: list[dict], now: datetime, allowed_symbols: set[str]) -> dict[str, list[dict]]:
    """Keep only relevant filings from the previous session close through now."""
    now = now.astimezone(IST)
    last_session = previous_trading_day(now.date())
    window_start = datetime.combine(last_session, time(15, 30), IST)
    selected: dict[str, list[dict]] = {}
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        symbol = str(record.get("symbol") or "").strip().upper()
        description = str(record.get("desc") or "").strip()
        title = str(record.get("attchmntText") or description).strip()
        raw_time = str(record.get("an_dt") or "")
        if symbol not in allowed_symbols or not any(term in description.casefold() or term in title.casefold() for term in MATERIAL_DESCRIPTIONS):
            continue
        try:
            published = datetime.strptime(raw_time, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
        except ValueError:
            continue
        if not window_start <= published <= now:
            continue
        url = str(record.get("attchmntFile") or "")
        if not url.startswith("https://nsearchives.nseindia.com/"):
            continue
        key = (symbol, description.casefold(), title.casefold())
        if key in seen:
            continue
        seen.add(key)
        category = "RESULTS" if "financial result" in title.casefold() or "financial result" in description.casefold() else description.upper()
        selected.setdefault(symbol, []).append({
            "title": title[:300], "url": url, "published_at": published.isoformat(),
            "source": "NSE filing", "period": "SAME DAY" if published.date() == now.date() else "PREVIOUS SESSION",
            "impact": "MATERIAL EVENT / DIRECTION UNVERIFIED", "context": description, "category": category,
        })
    for rows in selected.values():
        rows.sort(key=lambda row: (row["category"] == "RESULTS", row["published_at"]), reverse=True)
    return selected


def fetch_nse_filings(now: datetime, allowed_symbols: set[str]) -> dict[str, list[dict]]:
    """NSE can reject or time out; callers must retain other evidence on failure."""
    now = now.astimezone(IST)
    previous = previous_trading_day(now.date())
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
        "Accept": "application/json, text/plain, */*", "Accept-Language": "en-IN,en;q=0.9",
        "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
    })
    session.get("https://www.nseindia.com", timeout=8).raise_for_status()
    response = session.get(NSE_URL, params={
        "index": "equities", "from_date": previous.strftime("%d-%m-%Y"),
        "to_date": now.strftime("%d-%m-%Y"),
    }, timeout=15)
    response.raise_for_status()
    records = response.json()
    if not isinstance(records, list):
        raise ValueError("NSE announcements response is not a list")
    return select_filings(records, now, allowed_symbols)
