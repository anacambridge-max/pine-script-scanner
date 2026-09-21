from __future__ import annotations

from typing import Any
import math
import pandas as pd


def evaluate_chartink_filters(
    cash_5m: pd.DataFrame,
    cash_1m: pd.DataFrame,
    futures_5m: pd.DataFrame,
    *,
    futures_volume_multiple: float = 2.0,
    daily_high_min: float = 50.0,
) -> dict[str, Any]:
    """Replicate the supplied Chartink-style scanner conditions.

    Conditions:
      1) FUTURES: current 5m volume > 5m SMA(volume, 20) * 2
      2) CASH: current 5m high > previous trading-day high OR
              current 5m low < previous trading-day low
      3) CASH: current day's daily high > 50

    The filter is evaluated on completed 5-minute bars.
    """
    result = {
        "passed": False,
        "futures_volume_ok": False,
        "cash_break_ok": False,
        "daily_high_ok": False,
        "futures_volume": None,
        "futures_sma20": None,
        "futures_volume_multiple": None,
        "cash_5m_high": None,
        "cash_5m_low": None,
        "previous_day_high": None,
        "previous_day_low": None,
        "daily_high": None,
    }
    if cash_5m.empty or cash_1m.empty or futures_5m.empty:
        return result

    cash_5m = cash_5m.sort_values("timestamp").reset_index(drop=True)
    cash_1m = cash_1m.sort_values("timestamp").reset_index(drop=True)
    futures_5m = futures_5m.sort_values("timestamp").reset_index(drop=True)

    current_cash = cash_5m.iloc[-1]
    current_date = pd.Timestamp(current_cash["timestamp"]).date()
    history = cash_1m[pd.to_datetime(cash_1m["timestamp"]).dt.date < current_date]
    if history.empty:
        return result

    prior_days = sorted(pd.to_datetime(history["timestamp"]).dt.date.unique())
    previous_day = prior_days[-1]
    previous_rows = history[pd.to_datetime(history["timestamp"]).dt.date == previous_day]
    if previous_rows.empty:
        return result

    previous_day_high = float(previous_rows["high"].max())
    previous_day_low = float(previous_rows["low"].min())
    cash_5m_high = float(current_cash["high"])
    cash_5m_low = float(current_cash["low"])

    session = cash_1m[pd.to_datetime(cash_1m["timestamp"]).dt.date == current_date]
    daily_high = float(session["high"].max()) if not session.empty else math.nan

    vols = pd.to_numeric(futures_5m["volume"], errors="coerce")
    current_volume = float(vols.iloc[-1]) if pd.notna(vols.iloc[-1]) else math.nan
    sma20 = float(vols.tail(20).mean()) if len(vols.tail(20)) == 20 else math.nan
    volume_multiple = current_volume / sma20 if pd.notna(current_volume) and pd.notna(sma20) and sma20 > 0 else math.nan

    futures_volume_ok = bool(pd.notna(volume_multiple) and volume_multiple > futures_volume_multiple)
    cash_break_ok = bool(cash_5m_high > previous_day_high or cash_5m_low < previous_day_low)
    daily_high_ok = bool(pd.notna(daily_high) and daily_high > daily_high_min)

    result.update({
        "passed": futures_volume_ok and cash_break_ok and daily_high_ok,
        "futures_volume_ok": futures_volume_ok,
        "cash_break_ok": cash_break_ok,
        "daily_high_ok": daily_high_ok,
        "futures_volume": current_volume,
        "futures_sma20": sma20 if pd.notna(sma20) else None,
        "futures_volume_multiple": volume_multiple if pd.notna(volume_multiple) else None,
        "cash_5m_high": cash_5m_high,
        "cash_5m_low": cash_5m_low,
        "previous_day_high": previous_day_high,
        "previous_day_low": previous_day_low,
        "daily_high": daily_high if pd.notna(daily_high) else None,
    })
    return result
