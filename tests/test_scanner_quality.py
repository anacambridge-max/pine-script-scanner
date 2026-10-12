import pandas as pd
import pytest
from unittest.mock import Mock
from engine import PrimeConfig, PrimeEngine
from worker import scanner_worker
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


def test_aggregation_counts_missing_minutes_and_deduplicates():
    ts = pd.date_range("2026-10-12 09:15", periods=6, freq="min", tz="Asia/Kolkata")
    df = pd.DataFrame({"timestamp": ts, "open": 100., "high": 101., "low": 99., "close": 100., "volume": 10.})
    missing = df.drop(index=1)
    assert ScannerWorker._aggregate_ohlcv(missing, 3).source_count.tolist() == [2, 3]
    doubled = pd.concat([df, df.iloc[[0]]])
    bars = ScannerWorker._aggregate_ohlcv(doubled, 3)
    assert len(bars) == 2
    assert bars.volume.tolist() == [30., 30.]
    assert bars.source_count.tolist() == [3, 3]


def minute_history():
    ts = pd.date_range("2026-10-09 09:15", periods=120, freq="min", tz="Asia/Kolkata")
    return pd.DataFrame({"timestamp": ts, "open": 99.5, "high": 100., "low": 99., "close": 99.5, "volume": 1000.})


def test_partial_historical_bar_preserves_pdh_and_prevents_false_break():
    previous = minute_history()
    previous.loc[0, "high"] = 105.
    previous = previous.drop(index=1)
    current = pd.DataFrame({
        "timestamp": pd.date_range("2026-10-12 09:15", periods=3, freq="min", tz="Asia/Kolkata"),
        "open": [100., 100.5, 101.], "high": [100.5, 101., 102.2],
        "low": [99.9, 100.5, 101.], "close": [100.5, 101., 102.], "volume": 6000.,
    })
    frame = ScannerWorker._aggregate_ohlcv(pd.concat([previous, current], ignore_index=True), 3)
    result = PrimeEngine(PrimeConfig(signal_mode="QUALITY PRIME", use_ema_filter=True, require_follow_through=True)).evaluate(frame, 3)
    assert result["levels"]["pdh"] == 105.
    assert result["state"] != "CONFIRMED"


@pytest.mark.parametrize("missing", [[], [1], [4], [0, 1, 2]])
def test_worker_requires_complete_live_session_before_first_break_evaluation(monkeypatch, missing):
    current = pd.DataFrame({
        "timestamp": pd.date_range("2026-10-12 09:15", periods=6, freq="min", tz="Asia/Kolkata"),
        "open": 100., "high": 101., "low": 99., "close": 100., "volume": 1000.,
    }).drop(index=missing)
    data = pd.concat([minute_history(), current], ignore_index=True)
    clock = Mock(wraps=pd)
    clock.Timestamp.now.return_value = pd.Timestamp("2026-10-12 09:21:10", tz="Asia/Kolkata")
    monkeypatch.setattr(scanner_worker, "pd", clock)
    worker = ScannerWorker.__new__(ScannerWorker)
    worker.instrument_map = {"TEST": "TEST"}
    worker.engine = Mock()
    worker.engine.evaluate.return_value = {"state": "NO TRADE", "direction": "NEUTRAL"}
    worker._heartbeat = Mock()
    worker._on_bar("TEST", data)
    assert worker.engine.evaluate.call_count == (0 if missing else 1)


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
