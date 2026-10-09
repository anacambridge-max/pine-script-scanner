from datetime import datetime

import requests
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


def test_empty_preopen_payload_is_not_reported_as_success_with_empty_data_key(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    class FakeSession:
        pass
    monkeypatch.setattr(nse_premarket, "_nse_session", lambda: FakeSession())
    monkeypatch.setattr(nse_premarket, "_get_json", lambda session, url: {"data": []})
    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))
    assert result["status"] == "empty"
    assert result["rows"] == []


def test_nse_network_failure_is_retryable_not_success_on_first_attempt(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    def fail():
        raise RuntimeError("temporarily blocked")
    monkeypatch.setattr(nse_premarket, "_nse_session", fail)
    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))
    assert result["status"] == "unavailable"
    assert "temporarily blocked" in result["error"]


def test_empty_preopen_payload_is_not_reported_as_success_with_empty_rows_key(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    monkeypatch.setattr(nse_premarket, "_nse_session", lambda: object())
    monkeypatch.setattr(nse_premarket, "_get_json", lambda session, url: {"data": []})
    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))
    assert result["status"] == "empty"
    assert result["rows"] == []


def test_nse_network_failure_is_retryable_not_success_after_retry(tmp_path, monkeypatch):
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
    assert abs(parsed["indicative_gap_pct"] - 2.0) < 1e-9

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


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"HTTP {status}", response=response)


def test_nse_403_retries_with_fresh_session_then_succeeds(tmp_path, monkeypatch, caplog):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    sessions = []

    def fresh_session():
        session = object()
        sessions.append(session)
        return session

    calls = {"count": 0}

    def get_json(session, url):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _http_error(403)
        return {"data": []}

    monkeypatch.setattr(nse_premarket, "_nse_session", fresh_session)
    monkeypatch.setattr(nse_premarket, "_get_json", get_json)
    monkeypatch.setattr(nse_premarket.time_module, "sleep", lambda _seconds: None)

    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))

    assert result["status"] == "empty"
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    # Both NSE endpoints are retried with the fresh cookie-backed session.
    assert calls["count"] == 4
    assert "retry 1/2" in caplog.text


def test_nse_403_three_failed_attempts_gracefully_skip(tmp_path, monkeypatch, caplog):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    sessions = []

    def fresh_session():
        session = object()
        sessions.append(session)
        return session

    monkeypatch.setattr(nse_premarket, "_nse_session", fresh_session)
    monkeypatch.setattr(
        nse_premarket, "_get_json",
        lambda _session, _url: (_ for _ in ()).throw(_http_error(403)),
    )
    monkeypatch.setattr(nse_premarket.time_module, "sleep", lambda _seconds: None)

    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))

    assert result["status"] == "unavailable"
    assert len(sessions) == 3
    assert result["rows"] == []
    assert "graceful skip after attempt 3/3" in caplog.text


def test_oi_spurt_symbols_are_retained_even_without_preopen_rows(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    monkeypatch.setattr(
        nse_premarket,
        "_fetch_payloads_with_retry",
        lambda: (
            {"data": [{"metadata": {"symbol": "HAL", "previousClose": 100, "iep": 102}}]},
            {"data": [{"symbol": "BEL", "changeInOIPercent": 12.5, "volume": 250000}]},
        ),
    )
    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))
    assert result["status"] == "ok"
    by_symbol = {row["symbol"]: row for row in result["rows"]}
    assert {"HAL", "BEL"} <= set(by_symbol)
    assert by_symbol["BEL"]["oi_change_pct"] == 12.5
    assert by_symbol["BEL"]["indicative_price"] is None
    assert by_symbol["BEL"]["source_preopen"] is None
    assert by_symbol["BEL"]["source_oi"] == nse_premarket.OI_PAGE
    assert by_symbol["BEL"]["preopen_bias"] == "NEUTRAL / MIXED"


def test_oi_only_payload_is_a_valid_pre_market_snapshot(tmp_path, monkeypatch):
    study = nse_premarket.NSEPreMarketStudy(tmp_path / "nse.sqlite3")
    monkeypatch.setattr(
        nse_premarket,
        "_fetch_payloads_with_retry",
        lambda: (
            {"data": []},
            {"data": [{"symbol": "BEL", "changeInOIPercent": 8.0, "volume": 1000}]},
        ),
    )
    result = study.collect(datetime(2026, 10, 8, 9, 3, tzinfo=IST))
    assert result["status"] == "ok"
    assert len(result["rows"]) == 1
    assert result["rows"][0]["symbol"] == "BEL"


def test_oi_spurts_parses_pchange_in_oi_field():
    parsed = nse_premarket._flatten_oi({
        "symbol": "BEL",
        "pchangeInOI": "12.5",
        "volume": "250000",
    })
    assert parsed["oi_change_pct"] == 12.5
    assert parsed["oi_volume"] == 250000


def test_generic_price_pchange_is_not_used_as_oi_change():
    parsed = nse_premarket._flatten_oi({
        "symbol": "TCS",
        "pChange": 2.4,
        "volume": 5000,
    })
    assert parsed["oi_change_pct"] is None


def test_oi_percentage_can_be_derived_from_current_and_previous_oi():
    parsed = nse_premarket._flatten_oi({
        "symbol": "HAL",
        "latestOI": 1100,
        "prevOI": 1000,
    })
    assert parsed["oi_change_pct"] == 10.0

def test_partial_nse_source_failure_keeps_available_payload(monkeypatch):
    monkeypatch.setattr(nse_premarket, "_nse_session", lambda: object())

    def fake_get_json(_session, url):
        if url == nse_premarket.PREOPEN_API:
            return {"data": [{"symbol": "ABC"}]}
        raise requests.HTTPError("OI endpoint unavailable")

    monkeypatch.setattr(nse_premarket, "_get_json", fake_get_json)
    preopen, oi = nse_premarket._fetch_payloads_with_retry()
    assert preopen == {"data": [{"symbol": "ABC"}]}
    assert oi == {}

