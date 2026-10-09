from datetime import datetime
from zoneinfo import ZoneInfo
from worker.hot_news_core import (
    alias_matches, parse_published_at, freshness_weight, score_news,
    qualifies, SeenNewsStore, extract_stock_specific_text,
)

IST=ZoneInfo("Asia/Kolkata")

def test_rfc822_converts_to_ist():
    dt=parse_published_at("Thu, 08 Oct 2026 03:00:00 GMT")
    assert dt is not None and dt.hour == 8 and dt.minute == 30

def test_missing_or_naive_timestamp_gets_no_credit():
    assert parse_published_at(None) is None
    assert parse_published_at("2026-10-08T08:00:00") is None
    assert score_news("large order win", None)["news_score"] == 0

def test_recency_weight_and_stale_rejection():
    now=datetime(2026,10,8,9,0,tzinfo=IST)
    assert freshness_weight(now.replace(hour=8),now) == 1.0
    assert freshness_weight(now.replace(day=6,hour=8),now) == 0.0

def test_alias_word_boundaries():
    assert alias_matches("HAL receives order", ["HAL"])
    assert not alias_matches("HALO Technologies", ["HAL"])

def test_gate_requires_both_scores():
    assert qualifies(55, 7)
    assert not qualifies(54.9, 30)
    assert not qualifies(90, 0)

def test_seen_news_deduplicates(tmp_path):
    store=SeenNewsStore(tmp_path/"seen.sqlite3")
    assert store.is_new("https://example.com/a","large order win","HAL","test")
    assert not store.is_new("https://example.com/a","large order win","HAL","test")
    assert store.is_new("https://example.com/a","large order win","BEL","test")


def test_previous_session_after_close_news_survives_weekend():
    from worker.hot_news_core import freshness_weight
    now = datetime(2026, 10, 12, 8, 30, tzinfo=IST)  # Monday pre-open
    published = datetime(2026, 10, 9, 16, 0, tzinfo=IST)  # Friday after close
    assert freshness_weight(published, now) == 0.6


def test_news_outside_preopen_or_previous_close_window_is_rejected():
    from worker.hot_news_core import freshness_weight
    now = datetime(2026, 10, 8, 8, 30, tzinfo=IST)
    assert freshness_weight(datetime(2026, 10, 7, 14, 0, tzinfo=IST), now) == 0.0
    # The scan may finish at 09:15, but only news published by 09:00 is eligible.
    scan_finish = datetime(2026, 10, 8, 9, 10, tzinfo=IST)
    assert freshness_weight(datetime(2026, 10, 8, 8, 55, tzinfo=IST), scan_finish) == 1.0
    after_cutoff = datetime(2026, 10, 8, 9, 16, tzinfo=IST)
    assert freshness_weight(datetime(2026, 10, 8, 8, 55, tzinfo=IST), after_cutoff) == 0.0


def test_roundup_context_keeps_only_matching_stock_sentence():
    context = extract_stock_specific_text(
        "Stocks to watch today",
        "HAL wins a major order. BEL receives approval. Tata Motors launches a model.",
        ["BEL"],
    )
    assert "BEL receives approval" in context
    assert "HAL wins" not in context
    assert "Tata Motors" not in context


def test_atom_timestamp_parses_and_normalizes():
    dt = parse_published_at("2026-10-08T03:00:00Z")
    assert dt is not None and dt.hour == 8 and dt.minute == 30


def test_seen_news_deduplicates_same_headline_across_different_feeds(tmp_path):
    store = SeenNewsStore(tmp_path / "seen.sqlite3")
    assert store.is_new("https://feed-a.example/story?id=1", "HAL wins major defence order", "HAL", "feed-a")
    assert not store.is_new("https://feed-b.example/another-url", "HAL wins major defence order", "HAL", "feed-b")


def test_previous_trading_day_skips_nse_holiday():
    now = datetime(2026, 10, 21, 8, 30, tzinfo=IST)
    published = datetime(2026, 10, 19, 16, 0, tzinfo=IST)
    assert freshness_weight(published, now) == 0.6


def test_direction_classification_supports_hindi_without_changing_tier():
    from worker.hot_news_core import classify_direction, catalyst_tier
    text = "मिला ऑर्डर, बड़ा ऑर्डर और जुर्माना"
    assert classify_direction(text) == "mixed"
    assert catalyst_tier(text)[0] == "MATERIAL EVENT"


def test_configured_news_tier_scores_and_recency():
    from worker.hot_news_core import score_news
    now = datetime(2026, 10, 8, 8, 30, tzinfo=IST)
    fresh = score_news("HAL wins a large order", "2026-10-08T07:30:00+05:30", now)
    older = score_news("HAL wins a large order", "2026-10-08T01:30:00+05:30", now)
    assert fresh["news_score"] == 28
    assert older["news_score"] == 22
    assert fresh["direction"] == "positive"


def test_news_published_during_market_hours_is_not_preopen_news():
    now = datetime(2026, 10, 8, 8, 30, tzinfo=IST)
    published = datetime(2026, 10, 7, 12, 0, tzinfo=IST)
    assert freshness_weight(published, now) == 0.0


def test_current_day_news_after_0900_is_rejected():
    now = datetime(2026, 10, 8, 9, 8, tzinfo=IST)
    published = datetime(2026, 10, 8, 9, 1, tzinfo=IST)
    assert freshness_weight(published, now) == 0.0


def test_current_day_news_after_0900_is_rejected_even_during_late_scan():
    now = datetime(2026, 10, 8, 9, 8, tzinfo=IST)
    published = datetime(2026, 10, 8, 9, 1, tzinfo=IST)
    assert freshness_weight(published, now) == 0.0


# NSE pre-market source parsing and score checks
def test_nse_preopen_flatten_derives_gap_and_imbalance():
    from worker.nse_premarket import _flatten_preopen
    flat = _flatten_preopen({
        "metadata": {"symbol": "HAL", "previousClose": 100, "iep": 102},
        "detail": {"totalBuyQuantity": 700, "totalSellQuantity": 300, "finalQuantity": 1000},
    })
    assert flat["symbol"] == "HAL"
    assert flat["indicative_gap_pct"] == 2.0
    assert flat["imbalance_qty"] == 400
    assert flat["indicative_tradable_qty"] == 1000


def test_nse_oi_flatten_uses_oi_change_not_price_change():
    from worker.nse_premarket import _flatten_oi
    flat = _flatten_oi({"symbol": "BEL", "pChange": 3.2, "pchangeInOI": 12.5, "volume": 1000})
    assert flat["symbol"] == "BEL"
    assert flat["oi_change_pct"] == 12.5
    assert flat["oi_volume"] == 1000


def test_nse_oi_change_can_be_derived_from_oi_values():
    from worker.nse_premarket import _flatten_oi
    flat = _flatten_oi({"symbol": "HAL", "currentOI": 1100, "previousOI": 1000})
    assert flat["oi_change_pct"] == 10.0


def test_nse_preopen_score_direction_is_based_on_gap_and_order_imbalance():
    from worker.nse_premarket import _score_preopen
    score, bias, reasons = _score_preopen({
        "indicative_gap_pct": 2.5, "buy_qty": 800, "sell_qty": 200,
        "indicative_tradable_qty": 1000, "imbalance_qty": 600,
    })
    assert score == 50
    assert bias == "BULLISH BIAS"
    assert any("buy quantity" in reason for reason in reasons)


def test_nse_collector_never_fetches_outside_0900_to_0908(tmp_path, monkeypatch):
    from worker.nse_premarket import NSEPreMarketStudy, IST
    import worker.nse_premarket as module

    def fail_if_called():
        raise AssertionError("network must not be called outside the requested window")

    monkeypatch.setattr(module, "_fetch_payloads_with_retry", fail_if_called)
    study = NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    assert study.collect(datetime(2026, 10, 9, 8, 59, tzinfo=IST))["status"] == "outside_window"
    assert study.collect(datetime(2026, 10, 9, 9, 9, tzinfo=IST))["status"] == "outside_window"
    assert study.collect(datetime(2026, 10, 10, 9, 3, tzinfo=IST))["status"] == "outside_window"


def test_nse_collector_rejects_naive_datetime(tmp_path):
    from worker.nse_premarket import NSEPreMarketStudy
    assert NSEPreMarketStudy(tmp_path / "nse.sqlite3").collect(datetime(2026, 10, 9, 9, 3))["status"] == "invalid_time"
