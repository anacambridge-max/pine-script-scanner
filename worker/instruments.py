from __future__ import annotations

import gzip
import io
import os
from datetime import datetime
from typing import Any

import requests

UPSTOX_BOD_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"


def load_fno_stock_instruments() -> list[dict[str, Any]]:
    """Load current NSE stock-F&O underlyings from Upstox's BOD instrument file.

    We subscribe to the underlying NSE_EQ instruments, not the option contracts.
    Stock-F&O membership is derived from currently listed NSE_FO FUT contracts.
    """
    override = [x.strip() for x in os.getenv("UPSTOX_INSTRUMENT_KEYS", "").split(",") if x.strip()]
    if override:
        return [{"instrument_key": x, "trading_symbol": x.split("|", 1)[-1]} for x in override]

    response = requests.get(UPSTOX_BOD_URL, timeout=60)
    response.raise_for_status()
    raw = gzip.GzipFile(fileobj=io.BytesIO(response.content)).read()
    rows = __import__("json").loads(raw)

    today = datetime.now().date()
    eligible_underlyings: set[str] = set()
    underlying_symbols: dict[str, str] = {}

    # Build a definitive NSE_EQ instrument_key -> NSE trading symbol map.
    # Upstox NSE_EQ keys use the ISIN, while trading_symbol contains the actual
    # NSE symbol. This prevents ISINs from appearing in the scanner dashboard.
    for row in rows:
        if row.get("segment") == "NSE_EQ" and row.get("instrument_type") == "EQ":
            key = row.get("instrument_key")
            trading_symbol = row.get("trading_symbol")
            if key and trading_symbol:
                underlying_symbols[str(key)] = str(trading_symbol)

    for row in rows:
        if row.get("segment") != "NSE_FO":
            continue
        if row.get("instrument_type") != "FUT":
            continue
        if row.get("underlying_type") != "EQUITY":
            continue
        underlying = row.get("underlying_key")
        if not underlying or not underlying.startswith("NSE_EQ|"):
            continue

        expiry = row.get("expiry")
        if expiry is not None:
            try:
                expiry_date = datetime.fromtimestamp(float(expiry) / 1000).date()
                if expiry_date < today:
                    continue
            except (TypeError, ValueError, OverflowError):
                pass

        eligible_underlyings.add(underlying)
        # FUT rows also contain underlying_symbol; use it only as a fallback.
        symbol = row.get("underlying_symbol")
        if symbol and underlying not in underlying_symbols:
            underlying_symbols[underlying] = str(symbol)

    if not eligible_underlyings:
        raise RuntimeError("No current NSE stock-F&O underlyings found in Upstox instrument master")

    return [
        {
            "instrument_key": key,
            "trading_symbol": underlying_symbols.get(key, key.split("|", 1)[-1]),
        }
        for key in sorted(eligible_underlyings)
    ]
