import pandas as pd

from worker.scanner_worker import ScannerWorker


def test_previous_business_day_skips_weekend():
    assert ScannerWorker._previous_business_day(pd.Timestamp("2026-10-12")).date().isoformat() == "2026-10-09"


def test_previous_business_day_skips_nse_holiday():
    # 2026-10-20 is configured as an NSE holiday; the preceding valid session is 2026-10-19.
    assert ScannerWorker._previous_business_day(pd.Timestamp("2026-10-21")).date().isoformat() == "2026-10-19"


def test_previous_business_day_for_sunday_returns_friday():
    assert ScannerWorker._previous_business_day(pd.Timestamp("2026-10-11")).date().isoformat() == "2026-10-09"
