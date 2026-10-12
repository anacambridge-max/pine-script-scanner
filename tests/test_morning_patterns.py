import pandas as pd
from worker.morning_hot_scanner import MorningHotScanner


def test_quiet_nr7_watch_does_not_need_prior_day_extreme_volume():
    ts = pd.date_range("2026-09-01", periods=30, freq="B", tz="Asia/Kolkata")
    close = [100-i*.2 for i in range(30)]
    frame = pd.DataFrame({"timestamp": ts, "open": close, "close": close,
                          "high": [c+2 for c in close], "low": [c-2 for c in close], "volume": 100000})
    frame.loc[29, ["high", "low"]] = [close[-1]+.2, close[-1]-.2]
    scanner = MorningHotScanner()
    result = scanner._technical(frame, ts[-1].date())
    assert result["technical_score"] >= 55
    assert result["volume_multiple"] == 1
    assert "NR7" in result["reasons"]
    # Today's eventual rally must not change the pre-open ranking.
    future = pd.DataFrame([{ "timestamp": ts[-1]+pd.Timedelta(days=1), "open": 100,
                             "high": 200, "low": 90, "close": 190, "volume": 99999999}])
    assert scanner._technical(pd.concat([frame,future]), ts[-1].date()) == result
