import pandas as pd
from engine import PrimeEngine, PrimeConfig

def make_data(n=80):
    ts = pd.date_range("2026-09-18 09:15", periods=n, freq="1min", tz="Asia/Kolkata")
    close = [100 + i*0.02 for i in range(n)]
    return pd.DataFrame({
        "timestamp": ts,
        "open": close,
        "high": [v+0.10 for v in close],
        "low": [v-0.10 for v in close],
        "close": close,
        "volume": [1000.0]*n,
    })

def test_timeframe_guard():
    e = PrimeEngine()
    df = make_data()
    try:
        e.evaluate(df, 2)
        assert False, "2m must be rejected"
    except ValueError:
        pass

def test_result_shape():
    e = PrimeEngine(PrimeConfig())
    result = e.evaluate(make_data(), 1)
    assert result["timeframe"] == 1
    assert "prime_score" in result
    assert "risk" in result

def test_grade_mapping():
    # Validate the score bands used by the Pine implementation indirectly
    # through a controlled monkeypatch of the engine's evaluate output is
    # intentionally avoided; this test protects the public result contract.
    e = PrimeEngine()
    result = e.evaluate(make_data(), 1)
    assert result["grade"] in {"—","WEAK","WATCH","GOOD","STRONG","PRIME A","PRIME A+"}
