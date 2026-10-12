from worker.market_context import oi_evidence, candle_evidence
from worker.sector_ranker import SectorRanker
import time


def test_price_oi_uses_same_futures_contract_and_zero_is_not_missing():
    quote = {"oi": 110, "previous_oi": 100, "last_price": 102, "prev_close_price": 100}
    assert oi_evidence(quote)["label"] == "LONG BUILDUP"
    quote["oi"] = 90
    assert oi_evidence(quote)["label"] == "SHORT COVERING"
    quote["last_price"] = 98
    assert oi_evidence(quote)["label"] == "LONG UNWINDING"
    quote["oi"] = 110
    assert oi_evidence(quote)["label"] == "SHORT BUILDUP"
    quote["previous_oi"] = 0
    assert oi_evidence(quote)["change_pct"] is None
    assert oi_evidence(quote)["label"] == "OI DATA UNAVAILABLE"


def test_candle_detects_fade_even_on_positive_session():
    quote = {"ohlc": {"open": 100, "high": 120, "low": 100}, "last_price": 104, "prev_close_price": 99}
    result = candle_evidence(quote, {"trend": "DOWNTREND", "pdh": 101})
    assert "UPPER-WICK / FADE" in result["labels"]
    assert "COUNTERTREND REBOUND" in result["labels"]
    assert "ABOVE PDH" in result["labels"]
    assert "STRONG BULL BODY" not in result["labels"]


def test_sell_sector_ranks_weakest_first_and_stale_data_gives_no_bonus():
    ranker = SectorRanker.__new__(SectorRanker)
    ranker._symbol_sector = {"TEST": "WEAK"}
    ranker.refresh = lambda: None
    ranker._apply_ranked_changes({"STRONG": 2., "MIDDLE": 1., "FLAT": 0., "WEAK": -3.})
    result = ranker.get("TEST", "SELL")
    assert result["sector_rank"] == 1
    assert result["sector_bonus"] == 10
    assert result["sector_rank_type"] == "TOP 3 LOSER"
    assert ranker.get("TEST", "BUY")["sector_bonus"] == 0
    ranker._quote_time = time.time()-200
    assert ranker.get("TEST", "SELL")["sector_bonus"] == 0
