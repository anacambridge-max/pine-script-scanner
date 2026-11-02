from collections import defaultdict

import pandas as pd

from worker.upstox_feed import UpstoxV3Feed


def test_late_start_uses_intraday_endpoint_and_excludes_incomplete_minute(monkeypatch):
    feed = UpstoxV3Feed.__new__(UpstoxV3Feed)
    feed.access_token = "test-token"
    feed.instrument_keys = ["NSE_EQ|TEST"]
    feed._bars = defaultdict(dict)
    called = []

    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"data": {"candles": [
                ["2026-11-02T09:15:00+05:30", 100, 102, 99, 101, 500, 0],
                ["2026-11-02T09:22:00+05:30", 101, 103, 100, 102, 200, 0],
            ]}}

    def fake_get(url, **_kwargs):
        called.append(url)
        return Response()

    monkeypatch.setattr("worker.upstox_feed.requests.get", fake_get)
    feed.seed_current_session(pd.Timestamp("2026-11-02T09:22:30+05:30"))
    assert called == ["https://api.upstox.com/v3/historical-candle/intraday/NSE_EQ%7CTEST/minutes/1"]
    assert list(feed._bars["NSE_EQ|TEST"]) == [pd.Timestamp("2026-11-02T09:15:00+05:30")]
