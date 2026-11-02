"""Daily setup and current market evidence; independent of signal confirmation."""
from __future__ import annotations

import math
import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from engine.daily_context import daily_context
from worker.opening_study import opening_candle_evidence


def number(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def oi_evidence(quote: dict) -> dict:
    current, previous = number(quote.get("oi")), number(quote.get("previous_oi"))
    price, close = number(quote.get("last_price")), number(quote.get("prev_close_price"))
    oi_change = (current / previous - 1) * 100 if current is not None and previous and previous > 0 else None
    price_change = (price / close - 1) * 100 if price is not None and close and close > 0 else None
    label = "OI DATA UNAVAILABLE"
    if oi_change is not None and price_change is not None:
        if abs(oi_change) < 0.5 or abs(price_change) < 0.1:
            label = "MIXED / FLAT"
        else:
            label = ("LONG BUILDUP" if oi_change > 0 else "SHORT COVERING") if price_change > 0 else ("SHORT BUILDUP" if oi_change > 0 else "LONG UNWINDING")
    return {"label": label, "change_pct": oi_change, "futures_price_change_pct": price_change,
            "current": current, "previous": previous, "contract": quote.get("instrument_token"),
            "quote_time": quote.get("timestamp"), "interpretation": "Price/OI association, not a proven cause"}


def candle_evidence(quote: dict, daily: dict) -> dict:
    ohlc = quote.get("ohlc") or {}
    o, h, l, c = [number(value) for value in (ohlc.get("open"), ohlc.get("high"), ohlc.get("low"), quote.get("last_price"))]
    previous = number(quote.get("prev_close_price"))
    if any(value is None for value in (o, h, l, c)) or h < l or not previous or previous <= 0:
        return {"status": "MISSING"}
    width = h - l
    body = abs(c-o) / width if width else 0
    location = (c-l) / width if width else 0.5
    labels = []
    if body >= 0.6 and (location >= 0.75 if c > o else location <= 0.25):
        labels.append("STRONG BULL BODY" if c > o else "STRONG BEAR BODY")
    if width and (h-max(o,c))/width >= 0.4:
        labels.append("UPPER-WICK / FADE")
    if width and (min(o,c)-l)/width >= 0.4:
        labels.append("LOWER-WICK / RECOVERY")
    if daily.get("pdh") and c > daily["pdh"]:
        labels.append("ABOVE PDH")
    if daily.get("pdl") and c < daily["pdl"]:
        labels.append("BELOW PDL")
    if daily.get("trend") == "DOWNTREND" and c > o:
        labels.append("COUNTERTREND REBOUND")
    if daily.get("trend") == "UPTREND" and c > o:
        labels.append("UPTREND CONTINUATION ATTEMPT")
    return {"status": "READY", "open": o, "high": h, "low": l, "close": c,
            "change_pct": (c/previous-1)*100, "gap_pct": (o/previous-1)*100,
            "body_ratio": body, "close_location": location, "labels": labels}


class MarketContext:
    def __init__(self, worker):
        self.worker = worker
        self.day: str | None = None
        self.daily: dict[str, dict] = {}
        self.histories: dict[str, pd.DataFrame] = {}
        self.news: list[Any] = []
        self.news_at: datetime | None = None
        self.daily_articles: dict[str, list[dict]] = {}
        self.daily_articles_at: datetime | None = None
        self.last_refresh: datetime | None = None
        self.latest_rows: dict[str, dict] = {}
        self.session = requests.Session()
        self.session.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 502, 503, 504])))

    def refresh(self, force: bool = False) -> list[dict]:
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        if not force and self.last_refresh and (now-self.last_refresh).total_seconds() < 60:
            return []
        day = now.date().isoformat()
        if self.day != day:
            cache = Path(f"data/market-context-daily-{day}.json")
            if cache.exists():
                try:
                    saved = json.loads(cache.read_text())
                    self.histories = {key: pd.DataFrame(records).assign(timestamp=lambda x: pd.to_datetime(x.timestamp)) for key, records in saved.items()}
                except (ValueError, KeyError):
                    self.histories = {}
            if not self.histories:
                self.histories = self.worker.feed.get_daily_histories(lookback_days=90, to_date=now.date()-timedelta(days=1))
                if self.histories:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    temp = cache.with_suffix(".tmp")
                    temp.write_text(json.dumps({key: frame.to_dict("records") for key, frame in self.histories.items()}, default=str))
                    temp.replace(cache)
            if not self.histories:
                raise RuntimeError("Daily histories unavailable; will retry without marking the day ready")
            self.daily = {key: daily_context(frame, day) for key, frame in self.histories.items()}
            self.day = day
            self.news = []
            self.news_at = None
            self.daily_articles = {}
            self.daily_articles_at = None
        keys = [key for item in self.worker.instruments for key in (item["instrument_key"], item.get("futures_key")) if key]
        quotes = {}
        for offset in range(0, len(keys), 100):
            try:
                response = self.session.get("https://api.upstox.com/v3/market-quote/quotes",
                    params={"instrument_key": ",".join(keys[offset:offset+100])},
                    headers={"Accept": "application/json", "Authorization": f"Bearer {self.worker.access_token}"}, timeout=12)
                response.raise_for_status()
                for item in (response.json().get("data") or {}).values():
                    if item.get("instrument_token"):
                        quotes[item["instrument_token"]] = item
            except requests.RequestException as exc:
                print(f"[CONTEXT QUOTES] batch {offset//100+1} unavailable: {type(exc).__name__}")
        if not self.news_at or (now-self.news_at).total_seconds() >= 900:
            try:
                from worker.moneycontrol_news import fetch_moneycontrol_news
                self.news = fetch_moneycontrol_news(max_items=80, timestamped_only=True)
                self.news_at = now
            except Exception as exc:
                print(f"[CONTEXT NEWS WARNING] {type(exc).__name__}")
        if not self.daily_articles_at or (now-self.daily_articles_at).total_seconds() >= 900:
            try:
                from worker.daily_stock_articles import fetch_daily_stock_articles
                self.daily_articles = fetch_daily_stock_articles(self.worker.instruments, now)
                self.daily_articles_at = now
            except Exception as exc:
                self.daily_articles_at = now
                print(f"[DAILY ARTICLES WARNING] {type(exc).__name__}: {exc}")
        from worker.hot_news_core import alias_matches, extract_stock_specific_text, classify_direction, parse_published_at
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        rows = []
        for instrument in self.worker.instruments:
            key, symbol = instrument["instrument_key"], instrument["trading_symbol"]
            daily = self.daily.get(key, {"status": "MISSING"})
            quote = quotes.get(key, {})
            opening = opening_candle_evidence(
                self.worker.feed._bars.get(key, {}).copy(),
                self.worker.feed._last_emitted_ts.get(key),
                now,
                daily.get("previous_close"),
            ) if now.hour * 60 + now.minute >= 9 * 60 + 16 else {"status": "PENDING"}
            # Generated quote timestamp is insufficient: verify the OHLC session.
            session_ts = (quote.get("ohlc") or {}).get("ts")
            quote_day = pd.to_datetime(session_ts, unit="ms", utc=True).tz_convert("Asia/Kolkata").date().isoformat() if session_ts else None
            quote_valid = quote_day == day
            candle = candle_evidence(quote, daily) if quote_valid else {"status": "STALE / NO CURRENT SESSION"}
            sector = self.worker.sector_ranker.get(symbol, "BUY")
            futures = quotes.get(instrument.get("futures_key"), {})
            futures_ts = (futures.get("ohlc") or {}).get("ts")
            futures_day = pd.to_datetime(futures_ts, unit="ms", utc=True).tz_convert("Asia/Kolkata").date().isoformat() if futures_ts else None
            oi = oi_evidence(futures) if futures_day == day else oi_evidence({})
            aliases = [symbol, instrument.get("company_name") or symbol]
            matched = [item for item in self.news if alias_matches(item.title, aliases) or alias_matches(item.text, aliases)]
            headlines = []
            for item in matched:
                if not item.published_at:
                    continue
                try:
                    published = parse_published_at(item.published_at)
                    if published is None:
                        continue
                    if published.date() != now.date() or published > now:
                        continue
                    stock_text = extract_stock_specific_text(item.title, item.text, aliases)
                    headlines.append({"title": item.title, "url": item.url, "published_at": published.isoformat(),
                        "context": stock_text, "impact": classify_direction(stock_text).upper() + " MENTION"})
                except (ValueError, TypeError):
                    continue
            # Only compare session volume against complete daily volume at close.
            history = self.histories.get(key)
            volume_ratio = None
            if quote_valid and now.hour * 60 + now.minute >= 15*60+30 and history is not None:
                avg = number(history.volume.tail(20).mean())
                volume = number(quote.get("volume"))
                volume_ratio = volume/avg if volume is not None and avg and avg > 0 else None
            rows.append({"trade_date": day, "symbol": symbol, "instrument_key": key,
                "observed_at": now.isoformat(), "daily_context": daily, "sector_context": sector,
                "market_evidence": {"candle": candle, "oi": oi, "news": headlines[:5],
                    "daily_articles": self.daily_articles.get(symbol, [])[:8],
                    "opening": opening,
                    "quote_time": quote.get("timestamp"), "volume_vs_daily20": volume_ratio,
                    "news_status": "MATCHED" if headlines else "NO VERIFIED MATCH IN FETCHED COVERAGE"}})
        self.worker.supabase.write_market_context(rows)
        self.latest_rows = {row["instrument_key"]: row for row in rows}
        self.last_refresh = now
        return rows
