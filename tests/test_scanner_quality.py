import pandas as pd
import pytest
from engine import PrimeConfig, PrimeEngine
from worker.scanner_worker import ScannerWorker


def candles():
    timestamps = pd.date_range("2026-10-09 09:15", periods=40, freq="3min", tz="Asia/Kolkata")
    frame = pd.DataFrame({"timestamp": timestamps, "open": 99.5, "high": 100.0, "low": 99.0, "close": 99.5, "volume": 1000.0})
    signal = pd.DataFrame([{"timestamp": pd.Timestamp("2026-10-12 09:15", tz="Asia/Kolkata"), "open": 100.0, "high": 102.2, "low": 99.9, "close": 102.0, "volume": 6000.0}])
    return pd.concat([frame, signal], ignore_index=True)


def test_completed_session_skips_weekends_and_holidays():
    monday = pd.Timestamp("2026-10-12 11:00", tz="Asia/Kolkata")
    assert ScannerWorker._completed_session(monday).date().isoformat() == "2026-10-09"
    holiday = pd.Timestamp("2026-10-02 16:00", tz="Asia/Kolkata")
    assert ScannerWorker._completed_session(holiday).date().isoformat() == "2026-10-01"
    assert ScannerWorker._completed_session(monday.replace(hour=16)).date().isoformat() == "2026-10-12"


def test_aggregation_rejects_missing_and_duplicate_minutes():
    ts = pd.date_range("2026-10-12 09:15", periods=6, freq="min", tz="Asia/Kolkata")
    df = pd.DataFrame({"timestamp": ts, "open": 100., "high": 101., "low": 99., "close": 100., "volume": 10.})
    missing = df.drop(index=1)
    assert len(ScannerWorker._aggregate_ohlcv(missing, 3)) == 1
    doubled = pd.concat([df, df.iloc[[0]]])
    bars = ScannerWorker._aggregate_ohlcv(doubled, 3)
    assert len(bars) == 2
    assert bars.volume.tolist() == [30., 30.]


def test_quality_confirmation_rejects_weak_candle():
    cfg = PrimeConfig(signal_mode="QUALITY PRIME", use_ema_filter=True, require_follow_through=True)
    df = candles()
    assert PrimeEngine(cfg).evaluate(df, 3)["state"] == "CONFIRMED"
    df.loc[df.index[-1], "open"] = 101.9
    assert PrimeEngine(cfg).evaluate(df, 3)["state"] != "CONFIRMED"


def test_invalid_prices_are_rejected():
    df = candles()
    df.loc[df.index[-1], "high"] = 98.0
    with pytest.raises(ValueError, match="Invalid OHLCV"):
        PrimeEngine().evaluate(df, 3)


def test_buffer_and_close_time_are_enforced():
    df = candles()
    assert PrimeEngine(PrimeConfig(level_buffer_pct=3)).evaluate(df, 3)["state"] != "CONFIRMED"
    df.loc[df.index[-1], "timestamp"] = pd.Timestamp("2026-10-12 10:00", tz="Asia/Kolkata")
    assert PrimeEngine().evaluate(df, 3)["state"] != "CONFIRMED"


def test_daily_cache_is_invalidated_when_required_session_missing():
    worker = ScannerWorker.__new__(ScannerWorker)
    cutoff = pd.Timestamp("2026-10-12", tz="Asia/Kolkata")
    worker._daily_history_cache = {"2026-10-12": {"TEST": candles().iloc[:-1]}}
    worker._run_next_day_scan(cutoff)
    assert "2026-10-12" not in worker._daily_history_cache


def test_volume_score_distinguishes_qualified_volume_strength():
    df = candles()
    df.loc[df.index[-1], "volume"] = 2500.0
    lower = PrimeEngine().evaluate(df, 3)
    df.loc[df.index[-1], "volume"] = 6000.0
    higher = PrimeEngine().evaluate(df, 3)
    assert lower["state"] == higher["state"] == "CONFIRMED"
    assert lower["score_breakdown"]["volume"] < higher["score_breakdown"]["volume"]
