from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from worker.opening_study import opening_candle_evidence


IST = ZoneInfo("Asia/Kolkata")


def test_opening_candle_waits_for_completion_and_uses_previous_opening_volume():
    today = datetime(2026, 11, 2, 9, 16, tzinfo=IST)
    friday = datetime(2026, 10, 30, 9, 15, tzinfo=IST)
    opening = pd.Timestamp(today - timedelta(minutes=1))
    bars = {pd.Timestamp(friday + timedelta(minutes=i)): {"volume": 100} for i in range(15)}
    bars[opening] = {"open": 101, "high": 103, "low": 100, "close": 102.5, "volume": 1400}
    assert opening_candle_evidence(bars, None, today, 100)["status"] == "PENDING"
    result = opening_candle_evidence(bars, opening, today, 100)
    assert result["status"] == "READY"
    assert result["volume_multiple"] == 14
    assert result["baseline_bars"] == 15
    assert result["gap_pct"] == pytest.approx(1)
    assert result["move_pct"] == pytest.approx(2.5)
    assert result["baseline_session"] == "2026-10-30"


def test_opening_candle_requires_valid_baseline_and_previous_close():
    now = datetime(2026, 11, 2, 9, 17, tzinfo=IST)
    opening = pd.Timestamp(now.replace(hour=9, minute=15))
    bars = {opening: {"open": 101, "high": 103, "low": 100, "close": 102, "volume": 500}}
    assert opening_candle_evidence(bars, opening, now, 100)["status"] == "NO_VOLUME_BASELINE"
    assert opening_candle_evidence(bars, opening, now, None)["status"] == "INVALID"
    prior_close_ts = pd.Timestamp(datetime(2026, 10, 30, 15, 29, tzinfo=IST))
    bars[prior_close_ts] = {"close": 100, "volume": 100}
    assert opening_candle_evidence(bars, opening, now, None)["previous_close"] == 100
