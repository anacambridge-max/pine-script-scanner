import pandas as pd
from engine.daily_context import daily_context


def history():
    ts = pd.bdate_range("2026-09-01", periods=25, tz="Asia/Kolkata")
    return pd.DataFrame({"timestamp": ts, "open": 100., "high": 103., "low": 97., "close": 100., "volume": 1000.})


def test_nr_and_narrow_exclude_current_day_and_use_trading_sessions():
    x = history()
    x.loc[23, ["high", "low"]] = [100.5, 99.5]
    x.loc[24, ["high", "low"]] = [120., 80.]
    result = daily_context(x, x.timestamp.iloc[24])
    assert result["analysis_date"] == x.timestamp.iloc[23].date().isoformat()
    assert result["nr4"] and result["nr7"] and result["narrow_pd"]
    assert result["pdh"] == 100.5
    assert result["range_vs_prior20"] == 1 / 6


def test_nr4_is_not_automatically_nr7():
    x = history()
    x.loc[20, ["high", "low"]] = [100.2, 99.8]
    x.loc[24, ["high", "low"]] = [101., 99.]
    result = daily_context(x, x.timestamp.iloc[-1] + pd.Timedelta(days=1))
    assert result["nr4"] and not result["nr7"]


def test_missing_short_or_invalid_history_does_not_invent_compression():
    assert daily_context(pd.DataFrame(), "2026-10-12")["status"] == "MISSING"
    result = daily_context(history().head(2), "2026-10-12")
    assert not result["nr4"] and not result["nr7"] and not result["narrow_pd"]
    x = history()
    x.loc[24, "high"] = 90.
    assert daily_context(x, "2026-12-01")["status"] == "INVALID"
