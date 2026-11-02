"""Completed-session context, never using today's daily candle for a live signal."""
from __future__ import annotations

import numpy as np
import pandas as pd


def daily_context(history: pd.DataFrame, trade_date, narrow_ratio: float = 0.65) -> dict:
    if history.empty:
        return {"status": "MISSING"}
    x = history.copy()
    ts = pd.to_datetime(x.timestamp)
    ts = ts.dt.tz_localize("Asia/Kolkata") if ts.dt.tz is None else ts.dt.tz_convert("Asia/Kolkata")
    x["date"] = ts.dt.date
    x = x[x.date < pd.Timestamp(trade_date).date()].sort_values("timestamp")
    x = x.drop_duplicates("date", keep="last")
    if x.empty:
        return {"status": "MISSING"}
    values = x[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(values).all(axis=1) & values.close.gt(0) & values.low.gt(0) & values.volume.ge(0)
    valid &= values.high.ge(values[["open", "close", "low"]].max(axis=1))
    valid &= values.low.le(values[["open", "close", "high"]].min(axis=1))
    if not valid.all():
        return {"status": "INVALID"}
    x[values.columns] = values
    ranges = x.high - x.low
    row = x.iloc[-1]
    width = float(ranges.iloc[-1])
    baseline = ranges.iloc[:-1].tail(20)
    relative = width / float(baseline.mean()) if len(baseline) >= 10 and baseline.mean() > 0 else None
    nr4 = len(x) >= 4 and width > 0 and width <= float(ranges.tail(4).min())
    nr7 = len(x) >= 7 and width > 0 and width <= float(ranges.tail(7).min())
    narrow = relative is not None and width > 0 and relative <= narrow_ratio
    body = abs(float(row.close - row.open)) / width if width else 0.0
    upper = float(row.high - max(row.open, row.close)) / width if width else 0.0
    lower = float(min(row.open, row.close) - row.low) / width if width else 0.0
    location = float(row.close - row.low) / width if width else 0.5
    prior = x.iloc[:-1]
    inside = len(prior) > 0 and row.high <= prior.iloc[-1].high and row.low >= prior.iloc[-1].low
    ema = x.close.ewm(span=20, adjust=False).mean()
    trend = "UNKNOWN"
    if len(x) >= 20:
        slope = float(ema.iloc[-1] - ema.iloc[-6])
        trend = "UPTREND" if row.close > ema.iloc[-1] and slope > 0 else "DOWNTREND" if row.close < ema.iloc[-1] and slope < 0 else "MIXED"
    labels = [label for flag, label in [(nr7, "NR7"), (nr4, "NR4"), (narrow, "NARROW PD RANGE"), (inside, "INSIDE DAY")] if flag]
    if body <= 0.1:
        labels.append("SMALL BODY / DOJI")
    elif lower >= 0.5 and body <= 0.35:
        labels.append("LOWER-WICK REJECTION")
    elif upper >= 0.5 and body <= 0.35:
        labels.append("UPPER-WICK REJECTION")
    if len(prior) >= 20:
        span = float(prior.high.tail(20).max() - prior.low.tail(20).min())
        position = float(row.close - prior.low.tail(20).min()) / span if span else 0.5
        if position <= 0.2:
            labels.append("NEAR 20-SESSION LOW")
        elif position >= 0.8:
            labels.append("NEAR 20-SESSION HIGH")
    return {
        "version": 1, "status": "READY", "analysis_date": row.date.isoformat(),
        "nr4": bool(nr4), "nr7": bool(nr7), "narrow_pd": bool(narrow),
        "compression": bool(nr4 or nr7 or narrow), "inside_day": bool(inside),
        "pdh": float(row.high), "pdl": float(row.low), "range": width,
        "previous_close": float(row.close),
        "range_pct": width / float(row.close) * 100,
        "range_vs_prior20": relative, "narrow_threshold": narrow_ratio,
        "body_ratio": body, "upper_wick_ratio": upper, "lower_wick_ratio": lower,
        "close_location": location, "trend": trend, "labels": labels,
        "sessions": len(x),
    }
