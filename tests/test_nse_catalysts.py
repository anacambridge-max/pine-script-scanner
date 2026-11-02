from datetime import datetime
from zoneinfo import ZoneInfo

from worker.nse_catalysts import select_filings


def test_previous_session_and_same_day_filings_are_neutral_and_time_gated():
    now = datetime(2026, 11, 2, 9, 20, tzinfo=ZoneInfo("Asia/Kolkata"))
    records = [
        {"symbol": "DELHIVERY", "an_dt": "30-Oct-2026 16:39:08", "desc": "Outcome of Board Meeting",
         "attchmntText": "Financial results for September quarter", "attchmntFile": "https://nsearchives.nseindia.com/corporate/delhivery.pdf"},
        {"symbol": "DIXON", "an_dt": "02-Nov-2026 08:30:00", "desc": "Financial Results",
         "attchmntText": "Quarterly results", "attchmntFile": "https://nsearchives.nseindia.com/corporate/dixon.pdf"},
        {"symbol": "DIXON", "an_dt": "02-Nov-2026 10:00:00", "desc": "Financial Results",
         "attchmntText": "Later update", "attchmntFile": "https://nsearchives.nseindia.com/corporate/later.pdf"},
        {"symbol": "DELHIVERY", "an_dt": "31-Oct-2026 10:00:00", "desc": "Copy of Newspaper Publication",
         "attchmntText": "Quarterly financial results published", "attchmntFile": "https://nsearchives.nseindia.com/corporate/weekend.pdf"},
        {"symbol": "DELHIVERY", "an_dt": "30-Oct-2026 14:00:00", "desc": "Financial Results",
         "attchmntText": "Old filing", "attchmntFile": "https://nsearchives.nseindia.com/corporate/old.pdf"},
        {"symbol": "OTHER", "an_dt": "02-Nov-2026 08:00:00", "desc": "Financial Results",
         "attchmntText": "Other", "attchmntFile": "https://nsearchives.nseindia.com/corporate/other.pdf"},
    ]
    found = select_filings(records, now, {"DELHIVERY", "DIXON"})
    assert len(found["DELHIVERY"]) == 2
    assert len(found["DIXON"]) == 1
    assert found["DELHIVERY"][0]["period"] == "PREVIOUS SESSION"
    assert found["DIXON"][0]["period"] == "SAME DAY"
    assert all(row["impact"] == "MATERIAL EVENT / DIRECTION UNVERIFIED" for rows in found.values() for row in rows)
