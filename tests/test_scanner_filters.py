import pandas as pd
from engine.scanner_filters import evaluate_chartink_filters


def make_1m():
    parts = []
    for day in ["2026-09-17", "2026-09-18"]:
        ts = pd.date_range(
            f"{day} 09:15",
            periods=375,
            freq="1min",
            tz="Asia/Kolkata",
        )
        parts.append(pd.DataFrame({
            "timestamp": ts,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000.0,
        }))
    return pd.concat(parts, ignore_index=True)


def make_5m(df):
    return (
        df.set_index("timestamp")
        .resample("5min", origin="start_day", offset="15min")
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


def test_chartink_filter_requires_all_root_conditions():
    cash = make_1m()
    cash_5m = make_5m(cash)
    cash_5m.loc[cash_5m.index[-1], "high"] = 102.0

    # 20-bar futures baseline of 1000, current bar at 2500 -> >2x SMA.
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
    cash_5m = make_5m(cash)
    cash_5m.loc[cash_5m.index[-1], "high"] = 102.0

    futures_5m = cash_5m.copy()
    futures_5m["volume"] = 1000.0

    result = evaluate_chartink_filters(cash_5m, cash, futures_5m)
    assert result["passed"] is False
    assert result["futures_volume_ok"] is False
