from datetime import datetime
from zoneinfo import ZoneInfo
from worker.hot_news_core import (
    alias_matches, parse_published_at, freshness_weight, score_news,
    qualifies, SeenNewsStore,
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
