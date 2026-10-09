from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from worker.moneycontrol_news import NewsItem, match_news


class MorningHotScanner:
    """Direction-neutral pre-open F&O hot-stock scanner.

    Combines completed-session technical activity with fresh Moneycontrol
    catalyst/news context. It never assigns BUY or SELL.
    """

    def __init__(self, top_n: int = 5):
        self.top_n = top_n

    @staticmethod
    def _daily(one_minute: pd.DataFrame) -> pd.DataFrame:
        if one_minute.empty:
            return pd.DataFrame()
        x = one_minute.copy()
        x["timestamp"] = pd.to_datetime(x["timestamp"])
        x = x.sort_values("timestamp").set_index("timestamp")
        return (
            x.resample("1D")
            .agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
            )
            .dropna()
            .reset_index()
        )

    @staticmethod
    def _clamp(v: float) -> float:
        return max(0.0, min(100.0, float(v)))

    def _technical(
        self,
        one_minute: pd.DataFrame,
        analysis_date: date,
    ) -> dict[str, float] | None:
        daily = self._daily(one_minute)
        daily["date"] = daily["timestamp"].dt.date
        daily = daily[daily["date"] <= analysis_date].copy()
        if len(daily) < 22 or daily.iloc[-1]["date"] != analysis_date:
            return None

        row = daily.iloc[-1]
        prior20 = daily.iloc[-21:-1]
        prior10 = daily.iloc[-11:-1]
        prior5 = daily.iloc[-6:-1]

        close = float(row["close"])
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        prev_close = float(daily.iloc[-2]["close"])
        volume = float(row["volume"])

        rng = max(high - low, 1e-9)
        body_ratio = abs(close - open_) / rng
        change_pct = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0
        avg20_volume = float(prior20["volume"].mean())
        volume_multiple = volume / avg20_volume if avg20_volume else 0.0
        avg10_range = float((prior10["high"] - prior10["low"]).mean())
        range_expansion = rng / avg10_range if avg10_range else 0.0
        avg5_range = float((prior5["high"] - prior5["low"]).mean())
        compression = self._clamp((1 - avg5_range / avg10_range) * 100) if avg10_range else 0.0

        high20 = float(prior20["high"].max())
        low20 = float(prior20["low"].min())
        high_distance = abs(high20 - close) / close * 100 if close else 999
        low_distance = abs(close - low20) / close * 100 if close else 999
        proximity = self._clamp(100 - min(high_distance, low_distance) / 3 * 100)

        volume_score = self._clamp((volume_multiple - 1) / 2 * 100)
        body_score = self._clamp((body_ratio - 0.35) / 0.65 * 100)
        range_score = self._clamp((range_expansion - 0.8) / 1.0 * 100)
        move_score = self._clamp(abs(change_pct) / 6 * 100)

        technical = round(
            0.25 * volume_score
            + 0.20 * body_score
            + 0.15 * range_score
            + 0.15 * compression
            + 0.15 * proximity
            + 0.10 * move_score
        )

        reasons: list[str] = []
        if abs(change_pct) >= 2:
            reasons.append(f"D-1 move {change_pct:+.2f}%")
        if volume_multiple >= 1.5:
            reasons.append(f"Volume {volume_multiple:.1f}x 20D")
        if body_ratio >= 0.60:
            reasons.append("Strong daily body")
        if compression >= 40:
            reasons.append("Multi-day compression")
        if min(high_distance, low_distance) <= 2:
            reasons.append("Near 20D extreme")
        if range_expansion >= 1.1:
            reasons.append("Range expansion")

        return {
            "technical_score": technical,
            "avg_daily_volume": avg20_volume,
            "close": close,
            "change_percent": change_pct,
            "volume_multiple": volume_multiple,
            "body_ratio": body_ratio,
            "range_expansion": range_expansion,
            "compression_score": compression,
            "breakout_proximity": proximity,
            "high_distance": high_distance,
            "low_distance": low_distance,
            "reasons": reasons,
        }

    def scan_all(
        self,
        histories: dict[str, pd.DataFrame],
        instrument_map: dict[str, str],
        company_map: dict[str, str],
        analysis_date: date,
        news_items: list[NewsItem],
        scan_time: datetime | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        import json
        from pathlib import Path
        from worker.hot_news_core import load_aliases, alias_matches, extract_stock_specific_text, score_news, qualifies, SeenNewsStore
        from worker.hot_stocks_config import (
            MIN_TECH_SCORE, EXCLUDE_RESULTS_DAY, EXCLUDE_FO_BAN,
            EXCLUDE_LOW_LIQUIDITY, MIN_AVG_DAILY_VOLUME,
        )
        aliases_map = load_aliases()
        exclusions_path = Path(__file__).with_name("hot_stock_exclusions.json")
        try:
            exclusions = json.loads(exclusions_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            exclusions = {"results_dates": {}, "fo_ban_dates": {}}
        date_key = analysis_date.isoformat()
        results_today = set(exclusions.get("results_dates", {}).get(date_key, []))
        fo_ban_today = set(exclusions.get("fo_ban_dates", {}).get(date_key, []))
        seen_store = SeenNewsStore()
        hot_rows: list[dict[str, Any]] = []
        technical_rows: list[dict[str, Any]] = []
        for instrument_key, frame in histories.items():
            symbol = instrument_map.get(instrument_key, instrument_key.split("|", 1)[-1])
            company = company_map.get(instrument_key, symbol)
            try:
                tech = self._technical(frame, analysis_date)
                if not tech:
                    continue
                # Optional exclusion lists are deliberately opt-in and must be
                # maintained from official exchange/company calendars.
                if EXCLUDE_RESULTS_DAY and symbol in results_today:
                    continue
                if EXCLUDE_FO_BAN and symbol in fo_ban_today:
                    continue
                if EXCLUDE_LOW_LIQUIDITY and MIN_AVG_DAILY_VOLUME > 0:
                    if tech.get("avg_daily_volume", 0) < MIN_AVG_DAILY_VOLUME:
                        continue
                candidates = []
                for item in news_items:
                    aliases = list(dict.fromkeys([symbol, company] + aliases_map.get(symbol, [])))
                    title_match = alias_matches(item.title, aliases)
                    body_match = alias_matches(item.text, aliases)
                    if not (title_match or body_match):
                        continue
                    # Score only the headline and stock-specific roundup sentence(s).
                    # This prevents a catalyst for one company being assigned to every
                    # company mentioned elsewhere in the same roundup.
                    stock_context = extract_stock_specific_text(item.title, item.text, aliases)
                    scored = score_news(stock_context, item.published_at, now=scan_time)
                    if not scored["news_score"]:
                        continue
                    if not seen_store.is_new(item.url, item.title, symbol, getattr(item, "source", "") or item.url):
                        continue
                    candidates.append((scored, item, 1.0 if title_match else 0.5))
                if candidates:
                    candidates.sort(key=lambda x: (x[0]["news_score"] * x[2], x[0]["published_ist"] or ""), reverse=True)
                    scored, item, match_factor = candidates[0]
                    news_score = min(30, round(scored["news_score"] * match_factor))
                    news_impact = scored["direction"].upper() + " · " + scored["tier"]
                    news_titles = [{
                        "title": item.title[:240], "url": item.url, "impact": news_impact,
                        "source": getattr(item, "source", "") or item.url.split("/")[2],
                        "published_at": scored["published_ist"], "direction": scored["direction"]
                    }]
                    published_ist = scored["published_ist"]
                    news_source = news_titles[0]["source"]
                    direction = scored["direction"]
                else:
                    news_score, news_impact, news_titles = 0, "NO FRESH MATCH", []
                    published_ist, news_source, direction = None, None, "neutral"
                row = {
                    "trade_date": analysis_date.isoformat(), "symbol": symbol,
                    "instrument_key": instrument_key, "company_name": company,
                    "score": max(0, min(100, round(tech["technical_score"] * 0.70 + news_score))),
                    "technical_score": int(tech["technical_score"]), "news_score": int(news_score),
                    "close": tech["close"], "change_percent": tech["change_percent"],
                    "volume_multiple": tech["volume_multiple"], "body_ratio": tech["body_ratio"],
                    "range_expansion": tech["range_expansion"], "compression_score": tech["compression_score"],
                    "breakout_proximity": tech["breakout_proximity"], "news_impact": news_impact,
                    "news_summary": news_titles[0]["title"] if news_titles else None,
                    "news_titles": news_titles, "news_source": news_source,
                    "published_ist": published_ist, "direction": direction,
                    "reasons": list(tech["reasons"]) + ([f"Fresh news: {news_impact}"] if news_score else ["No eligible fresh news"]),
                    "setup": "TODAY HOT STOCK" if qualifies(tech["technical_score"], news_score, MIN_TECH_SCORE) else "TECHNICAL ONLY WATCH",
                }
                if qualifies(tech["technical_score"], news_score, MIN_TECH_SCORE):
                    hot_rows.append(row)
                elif tech["technical_score"] >= MIN_TECH_SCORE:
                    technical_rows.append(row)
            except Exception as exc:
                print(f"[MORNING HOT WARNING] {symbol}: {exc}")
        key=lambda x: (x["score"], x["news_score"], x["technical_score"])
        return sorted(hot_rows, key=key, reverse=True)[:self.top_n], sorted(technical_rows, key=key, reverse=True)[:self.top_n]

    def scan(
        self, histories: dict[str, pd.DataFrame], instrument_map: dict[str, str],
        company_map: dict[str, str], analysis_date: date, news_items: list[NewsItem],
    ) -> list[dict[str, Any]]:
        return self.scan_all(histories, instrument_map, company_map, analysis_date, news_items)[0]
