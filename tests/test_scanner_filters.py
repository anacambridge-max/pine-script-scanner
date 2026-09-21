import pandas as pd
from engine.scanner_filters import evaluate_chartink_filters


def make_1m(days=2):
    ts = pd.date_range(
        "2026-09-17 09:15",
        periods=2 * 375,
        freq="1min",
        tz="Asia/Kolkata",
    )
    # Keep the synthetic session structure simple and deterministic.
    close = [100.0] * len(ts)
    high = [101.0] * len(ts)
    low = [99.0] * len(ts)
    volume = [1000.0] * len(ts)
    return pd.DataFrame({
        "timestamp": ts,
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def test_chartink_filter_requires_all_root_conditions():
    cash = make_1m()
    cash_5m = (
        cash.set_index("timestamp")
        .resample("5min", origin="start_day", offset="15min")
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
             close=("close", "last"), volume=("volume", "sum"))
        .dropna()
        .reset_index()
    )

    # Create a current 5m cash breakout above previous-day high.
    cash_5m.loc[cash_5m.index[-1], "high"] = 102.0

    # 20-bar futures volume baseline of 1000, current bar at 2500 -> 2.5x.
    futures_5m = cash_5m.copy()
    futures_5m["volume"] = 1000.0
    futures_5m.loc[futures_5m.index[-1], "volume"] = 2500.0

    result = evaluate_chartink_filters(
        cash_5m, cash, futures_5m,
        futures_volume_multiple=2.0,
        daily_high_min=50.0,
    )
    assert result["passed"] is True


def test_chartink_filter_blocks_low_futures_volume():
    cash = make_1m()
    cash_5m = (
        cash.set_index("timestamp")
        .resample("5min", origin="start_day", offset="15min")
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
             close=("close", "last"), volume=("volume", "sum"))
        .dropna()
        .reset_index()
    )
    cash_5m.loc[cash_5m.index[-1], "high"] = 102.0

    futures_5m = cash_5m.copy()
    futures_5m["volume"] = 1000.0

    result = evaluate_chartink_filters(cash_5m, cash, futures_5m)
    assert result["passed"] is False
    assert result["futures_volume_ok"] is False
