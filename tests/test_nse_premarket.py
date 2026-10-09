from datetime import datetime
from zoneinfo import ZoneInfo

from worker import nse_premarket


IST = ZoneInfo("Asia/Kolkata")


def test_preopen_parser_reads_nested_nse_shape():
    row = {
        "metadata": {
            "symbol": "ABC",
            "previousClose": 100,
            "iep": 103,
            "pChange": 3.0,
        },
        "detail": {
            "totalBuyQuantity": 90000,
            "totalSellQuantity": 20000,
            "finalQuantity": 15000,
        },
    }
    parsed = nse_premarket._flatten_preopen(row)
    assert parsed["symbol"] == "ABC"
    assert parsed["indicative_gap_pct"] == 3.0
    assert parsed["buy_qty"] == 90000
    assert parsed["sell_qty"] == 20000
    assert parsed["imbalance_qty"] == 70000


def test_preopen_gap_produces_bias_but_not_trade_signal():
    parsed = nse_premarket._flatten_preopen({
        "symbol": "XYZ",
        "previousClose": 200,
        "iep": 206,
        "totalBuyQuantity": 800,
        "totalSellQuantity": 100,
    })
    score, bias, reasons = nse_premarket._score_preopen(parsed)
    assert score > 0
    assert bias == "BULLISH BIAS"
    assert reasons
    assert "BUY" not in bias


def test_oi_parser_keeps_oi_as_separate_context():
    parsed = nse_premarket._flatten_oi({
        "symbol": "ABC",
        "changeInOIPercent": "12.5",
        "volume": "250000",
    })
    assert parsed["symbol"] == "ABC"
    assert parsed["oi_change_pct"] == 12.5
    assert parsed["oi_volume"] == 250000


def test_missing_preopen_values_remain_unknown_not_fabricated():
    parsed = nse_premarket._flatten_preopen({"symbol": "ABC"})
    assert parsed["indicative_gap_pct"] is None
    score, bias, _ = nse_premarket._score_preopen(parsed)
    assert score == 0
    assert bias == "NEUTRAL / MIXED"


def test_collection_only_runs_inside_0900_to_0908(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    def fail_if_called():
        raise AssertionError("network must not be called outside the study window")
    monkeypatch.setattr(nse_premarket, "_nse_session", fail_if_called)
    before = datetime(2026, 10, 8, 8, 59, tzinfo=IST)
    after = datetime(2026, 10, 8, 9, 9, tzinfo=IST)
    weekend = datetime(2026, 10, 10, 9, 3, tzinfo=IST)
    assert study.collect(before)["status"] == "outside_window"
    assert study.collect(after)["status"] == "outside_window"
    assert study.collect(weekend)["status"] == "outside_window"


def test_empty_preopen_payload_is_not_reported_as_success(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    class FakeSession:
        pass
    monkeypatch.setattr(nse_premarket, "_nse_session", lambda: FakeSession())
    monkeypatch.setattr(nse_premarket, "_get_json", lambda session, url: {"data": []})
    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))
    assert result["status"] == "empty"
    assert result["rows"] == []


def test_nse_network_failure_is_retryable_not_success(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    def fail():
        raise RuntimeError("temporarily blocked")
    monkeypatch.setattr(nse_premarket, "_nse_session", fail)
    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))
    assert result["status"] == "unavailable"
    assert "temporarily blocked" in result["error"]


def test_empty_preopen_payload_is_not_reported_as_success(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    monkeypatch.setattr(nse_premarket, "_nse_session", lambda: object())
    monkeypatch.setattr(nse_premarket, "_get_json", lambda session, url: {"data": []})
    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))
    assert result["status"] == "empty"
    assert result["rows"] == []


def test_nse_network_failure_is_retryable_not_success(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    def fail():
        raise RuntimeError("temporarily blocked")
    monkeypatch.setattr(nse_premarket, "_nse_session", fail)
    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))
    assert result["status"] == "unavailable"
    assert "temporarily blocked" in result["error"]

def test_oi_absolute_change_is_not_mislabeled_as_percentage():
    parsed = nse_premarket._flatten_oi({
        "symbol": "ABC",
        "changeInOI": 250000,
        "volume": 1000000,
    })
    assert parsed["oi_change_pct"] is None
    assert parsed["oi_volume"] == 1000000


def test_preopen_parser_reads_nested_preopen_market_object():
    parsed = nse_premarket._flatten_preopen({
        "metadata": {"symbol": "HAL", "previousClose": 1000},
        "detail": {"preOpenMarket": {
            "IEP": 1020,
            "totalBuyQuantity": 8000,
            "totalSellQuantity": 2000,
            "finalQuantity": 5000,
        }},
    })
    assert parsed["symbol"] == "HAL"
    assert parsed["indicative_price"] == 1020
    assert parsed["buy_qty"] == 8000
    assert parsed["sell_qty"] == 2000
    assert parsed["indicative_gap_pct"] == 2.0

def test_collect_can_restrict_rows_to_fno_universe(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    monkeypatch.setattr(nse_premarket, "_nse_session", lambda: object())
    payload = {"data": [
        {"metadata": {"symbol": "HAL", "previousClose": 100, "iep": 102}},
        {"metadata": {"symbol": "NONFNO", "previousClose": 100, "iep": 103}},
    ]}
    monkeypatch.setattr(
        nse_premarket, "_get_json",
        lambda session, url: payload if "pre-open" in url else {"data": []},
    )
    result = study.collect(
        datetime(2026, 10, 8, 9, 3, tzinfo=IST),
        allowed_symbols={"HAL"},
    )
    assert result["status"] == "ok"
    assert [row["symbol"] for row in result["rows"]] == ["HAL"]
