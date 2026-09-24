from __future__ import annotations

from datetime import date
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

    def scan(
        self,
        histories: dict[str, pd.DataFrame],
        instrument_map: dict[str, str],
        company_map: dict[str, str],
        analysis_date: date,
        news_items: list[NewsItem],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for instrument_key, frame in histories.items():
            symbol = instrument_map.get(instrument_key, instrument_key.split("|", 1)[-1])
            company = company_map.get(instrument_key, symbol)
            try:
                tech = self._technical(frame, analysis_date)
                if not tech:
                    continue
                news_score, news_impact, news_titles = match_news(symbol, company, news_items)
                score = round(tech["technical_score"] * 0.70 + news_score)
                reasons = list(tech["reasons"])
                if news_titles:
                    reasons.append(f"Moneycontrol: {news_impact}")
                rows.append({
                    "trade_date": analysis_date.isoformat(),
                    "symbol": symbol,
                    "instrument_key": instrument_key,
                    "company_name": company,
                    "score": max(0, min(100, score)),
                    "technical_score": int(tech["technical_score"]),
                    "news_score": int(news_score),
                    "close": tech["close"],
                    "change_percent": tech["change_percent"],
                    "volume_multiple": tech["volume_multiple"],
                    "body_ratio": tech["body_ratio"],
                    "range_expansion": tech["range_expansion"],
                    "compression_score": tech["compression_score"],
                    "breakout_proximity": tech["breakout_proximity"],
                    "news_impact": news_impact,
                    "news_summary": news_titles[0]["title"] if news_titles else None,
                    "news_titles": news_titles,
                    "reasons": reasons,
                    "setup": "TODAY HOT STOCK",
                })
            except Exception:
                continue

        # News-only F&O names are also considered. Their technical score is
        # zero, so strong catalyst names can still enter the watchlist.
        existing = {row["symbol"] for row in rows}
        for instrument_key, symbol in instrument_map.items():
            if symbol in existing:
                continue
            company = company_map.get(instrument_key, symbol)
            news_score, news_impact, news_titles = match_news(symbol, company, news_items)
            if news_score <= 0:
                continue
            rows.append({
                "trade_date": analysis_date.isoformat(),
                "symbol": symbol,
                "instrument_key": instrument_key,
                "company_name": company,
                "score": news_score,
                "technical_score": 0,
                "news_score": int(news_score),
                "close": None,
                "change_percent": None,
                "volume_multiple": None,
                "body_ratio": None,
                "range_expansion": None,
                "compression_score": None,
                "breakout_proximity": None,
                "news_impact": news_impact,
                "news_summary": news_titles[0]["title"] if news_titles else None,
                "news_titles": news_titles,
                "reasons": [f"Moneycontrol: {news_impact}"],
                "setup": "NEWS CATALYST",
            })

        return sorted(rows, key=lambda x: (x["score"], x["news_score"], x["technical_score"]), reverse=True)[: self.top_n]
