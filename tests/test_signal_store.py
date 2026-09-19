from worker.signal_store import DailySignalStore

def test_signal_store_deduplicates(tmp_path):
    store = DailySignalStore(str(tmp_path / "signals.json"))
    base = {
        "symbol": "NSE_EQ|TEST",
        "timeframe": 5,
        "direction": "BUY",
        "state": "CONFIRMED",
        "timestamp": "2026-09-19T09:20:00+05:30",
        "prime_score": 85,
    }
    assert store.add_confirmed(base) is True
    assert store.add_confirmed({**base, "timestamp": "2026-09-19T09:25:00+05:30"}) is False
    assert len(store.today()) == 1

def test_signal_store_ignores_non_confirmed(tmp_path):
    store = DailySignalStore(str(tmp_path / "signals.json"))
    base = {
        "symbol": "NSE_EQ|TEST",
        "timeframe": 5,
        "direction": "BUY",
        "state": "SETUP",
        "timestamp": "2026-09-19T09:20:00+05:30",
    }
    assert store.add_confirmed(base) is False
    assert store.today() == []
