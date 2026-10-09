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
    after_cutoff = datetime(2026, 10, 8, 9, 5, tzinfo=IST)
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
