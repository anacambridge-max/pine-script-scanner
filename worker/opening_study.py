"""Evidence from a completed 09:15 NSE one-minute candle.

This is a movement watch, not a trade signal. Its volume reference is the
previous completed session's first 15 one-minute bars, so the comparison is
explicit and does not imply institutional activity.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import pandas as pd


def opening_candle_evidence(
    bars: dict[pd.Timestamp, dict[str, Any]],
    completed_through: pd.Timestamp | None,
    now: datetime,
    previous_close: float | None,
) -> dict[str, Any]:
    day = now.date()
    if now.hour * 60 + now.minute < 9 * 60 + 16:
        return {"status": "PENDING"}
    opening_ts = pd.Timestamp(now).replace(hour=9, minute=15, second=0, microsecond=0)
    if completed_through is None or completed_through < opening_ts:
        return {"status": "PENDING"}
    candle = bars.get(opening_ts)
    if not candle:
        return {"status": "MISSING_OPENING_CANDLE"}
    dates = sorted({ts.date() for ts in bars if ts.date() < day})
    prior_day = dates[-1] if dates else None
    if previous_close is None and prior_day:
        prior_bars = sorted((ts, row) for ts, row in bars.items() if ts.date() == prior_day)
        # A partial prior-session seed is not a reliable previous close.
        if prior_bars and (prior_bars[-1][0].hour, prior_bars[-1][0].minute) >= (15, 20):
            previous_close = prior_bars[-1][1].get("close")
    try:
        o, h, l, c, volume = (float(candle[k]) for k in ("open", "high", "low", "close", "volume"))
        prior_close = float(previous_close) if previous_close is not None else 0.0
    except (TypeError, ValueError, KeyError):
        return {"status": "INVALID"}
    if not all(math.isfinite(value) for value in (o, h, l, c, volume, prior_close)) or min(o, l, c, prior_close) <= 0 or volume <= 0 or h < max(o, c, l) or l > min(o, c, h):
        return {"status": "INVALID"}

    baseline = []
    if prior_day:
        baseline = [float(row.get("volume") or 0) for ts, row in bars.items()
                    if ts.date() == prior_day and (9, 15) <= (ts.hour, ts.minute) < (9, 30)
                    and math.isfinite(float(row.get("volume") or 0)) and float(row.get("volume") or 0) > 0]
    baseline_mean = sum(baseline) / len(baseline) if len(baseline) >= 10 else None
    width = h - l
    return {
        "status": "READY" if baseline_mean else "NO_VOLUME_BASELINE",
        "timestamp": opening_ts.isoformat(),
        "previous_close": prior_close,
        "open": o, "high": h, "low": l, "close": c, "volume": volume,
        "gap_pct": (o / prior_close - 1) * 100,
        "move_pct": (c / prior_close - 1) * 100,
        "body_ratio": abs(c - o) / width if width > 0 else 0,
        "close_location": (c - l) / width if width > 0 else 0.5,
        "volume_multiple": volume / baseline_mean if baseline_mean else None,
        "baseline_bars": len(baseline),
        "baseline_session": prior_day.isoformat() if prior_day else None,
        "volume_reference": "previous session 09:15-09:29 average 1-minute volume",
    }
