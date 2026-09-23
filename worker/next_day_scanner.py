from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd


class NextDayScanner:
    """
    D-1 -> next-session candidate scanner.

    This is a watchlist generator, not the live entry engine. It uses only
    completed daily candles built from the worker's 1-minute history and ranks
    F&O stock underlyings. The live 3-minute PDH/PDL engine remains the
    confirmation layer on the following session.
    """

    def __init__(self, top_n: int = 3):
        self.top_n = top_n

    @staticmethod
    def _daily(one_minute: pd.DataFrame) -> pd.DataFrame:
        if one_minute.empty:
            return pd.DataFrame()
        x = one_minute.copy()
        x["timestamp"] = pd.to_datetime(x["timestamp"])
        x = x.sort_values("timestamp").set_index("timestamp")
        daily = (
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
        daily["date"] = daily["timestamp"].dt.date
        return daily

    @staticmethod
    def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
        return max(lo, min(hi, float(v)))

    def _score_symbol(
        self,
        symbol: str,
        company_name: str,
        one_minute: pd.DataFrame,
        analysis_date: date,
    ) -> dict[str, Any] | None:
        daily = self._daily(one_minute)
        daily = daily[daily["date"] <= analysis_date].copy()
        if len(daily) < 22:
            return None

        row = daily.iloc[-1]
        if row["date"] != analysis_date:
            return None

        prev = daily.iloc[-2]
        prior20 = daily.iloc[-21:-1]
        prior10 = daily.iloc[-11:-1]
        prior5 = daily.iloc[-6:-1]

        close = float(row["close"])
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        prev_close = float(prev["close"])
        volume = float(row["volume"])

        rng = max(high - low, 0.000001)
        body_ratio = abs(close - open_) / rng
        close_location = (close - low) / rng
        change_pct = ((close - prev_close) / prev_close * 100.0) if prev_close else 0.0

        avg20_volume = float(daily.iloc[-21:-1]["volume"].mean())
        volume_multiple = volume / avg20_volume if avg20_volume else 0.0

        avg10_range = float((prior10["high"] - prior10["low"]).mean())
        range_expansion = rng / avg10_range if avg10_range else 0.0

        prior5_ranges = prior5["high"] - prior5["low"]
        avg5_range = float(prior5_ranges.mean()) if len(prior5_ranges) else 0.0
        compression_score = self._clamp(
            (1.0 - (avg5_range / avg10_range if avg10_range else 1.0)) * 100.0,
            0,
            100,
        )

        highest20 = float(prior20["high"].max())
        lowest20 = float(prior20["low"].min())
        upside_distance = ((highest20 - close) / close * 100.0) if close else 999.0
        downside_distance = ((close - lowest20) / close * 100.0) if close else 999.0

        bullish = close > open_ and close_location >= 0.60
        bearish = close < open_ and close_location <= 0.40

        # Score each direction independently so the D-1 watchlist can return
        # separate BUY and SELL candidates.
        volume_score = self._clamp((volume_multiple - 1.0) / 2.0 * 100.0)
        body_score = self._clamp((body_ratio - 0.35) / 0.65 * 100.0)
        range_score = self._clamp((range_expansion - 0.8) / 1.0 * 100.0)
        compression = compression_score

        buy_proximity = self._clamp(100.0 - (upside_distance / 3.0 * 100.0))
        sell_proximity = self._clamp(100.0 - (downside_distance / 3.0 * 100.0))

        momentum_buy = self._clamp(50.0 + change_pct * 12.0)
        momentum_sell = self._clamp(50.0 - change_pct * 12.0)

        buy_score = round(
            25.0 * volume_score / 100.0
            + 20.0 * body_score / 100.0
            + 15.0 * range_score / 100.0
            + 15.0 * compression / 100.0
            + 15.0 * buy_proximity / 100.0
            + 10.0 * momentum_buy / 100.0
        )
        sell_score = round(
            25.0 * volume_score / 100.0
            + 20.0 * body_score / 100.0
            + 15.0 * range_score / 100.0
            + 15.0 * compression / 100.0
            + 15.0 * sell_proximity / 100.0
            + 10.0 * momentum_sell / 100.0
        )

        candidates: list[dict[str, Any]] = []
        if bullish and buy_score >= 55:
            reasons = []
            if volume_multiple >= 1.5:
                reasons.append(f"Volume {volume_multiple:.1f}x 20D")
            if body_ratio >= 0.60:
                reasons.append("Strong bullish body")
            if compression >= 40:
                reasons.append("Multi-day compression")
            if upside_distance <= 2.0:
                reasons.append("Near 20D high")
            if range_expansion >= 1.1:
                reasons.append("Range expansion")
            candidates.append(self._row(
                symbol, company_name, analysis_date, "BUY", buy_score,
                row, change_pct, volume_multiple, body_ratio, close_location,
                range_expansion, compression, buy_proximity, reasons,
                highest20, lowest20,
            ))

        if bearish and sell_score >= 55:
            reasons = []
            if volume_multiple >= 1.5:
                reasons.append(f"Volume {volume_multiple:.1f}x 20D")
            if body_ratio >= 0.60:
                reasons.append("Strong bearish body")
            if compression >= 40:
                reasons.append("Multi-day compression")
            if downside_distance <= 2.0:
                reasons.append("Near 20D low")
            if range_expansion >= 1.1:
                reasons.append("Range expansion")
            candidates.append(self._row(
                symbol, company_name, analysis_date, "SELL", sell_score,
                row, change_pct, volume_multiple, body_ratio, close_location,
                range_expansion, compression, sell_proximity, reasons,
                highest20, lowest20,
            ))

        if not candidates:
            return None
        return candidates

    @staticmethod
    def _row(
        symbol: str, company_name: str, analysis_date: date, direction: str,
        score: int, row: pd.Series, change_pct: float, volume_multiple: float,
        body_ratio: float, close_location: float, range_expansion: float,
        compression: float, proximity: float, reasons: list[str],
        highest20: float, lowest20: float,
    ) -> dict[str, Any]:
        grade = (
            "PRIME A+" if score >= 90 else
            "PRIME A" if score >= 80 else
            "STRONG" if score >= 70 else
            "GOOD" if score >= 60 else
            "WATCH"
        )
        return {
            "analysis_date": analysis_date.isoformat(),
            "symbol": symbol,
            "company_name": company_name,
            "direction": direction,
            "score": int(max(0, min(100, score))),
            "grade": grade,
            "close": float(row["close"]),
            "change_percent": float(change_pct),
            "volume_multiple": float(volume_multiple),
            "body_ratio": float(body_ratio),
            "close_location": float(close_location),
            "range_expansion": float(range_expansion),
            "compression_score": float(compression),
            "breakout_proximity": float(proximity),
            "setup": "D-1 PRE-MOVE",
            "reasons": reasons,
            "metrics": {
                "20d_high": highest20,
                "20d_low": lowest20,
            },
        }

    def scan(
        self,
        histories: dict[str, pd.DataFrame],
        instrument_map: dict[str, str],
        company_map: dict[str, str],
        analysis_date: date,
    ) -> list[dict[str, Any]]:
        all_rows: list[dict[str, Any]] = []
        for instrument_key, frame in histories.items():
            symbol = instrument_map.get(instrument_key, instrument_key.split("|", 1)[-1])
            company = company_map.get(instrument_key, symbol)
            try:
                rows = self._score_symbol(symbol, company, frame, analysis_date)
                if rows:
                    all_rows.extend(rows)
            except Exception:
                continue

        # The user-facing objective is a small 2–3 stock watchlist, not a
        # six-stock list. Keep the strongest movers regardless of direction.
        return sorted(all_rows, key=lambda x: x["score"], reverse=True)[: self.top_n]
