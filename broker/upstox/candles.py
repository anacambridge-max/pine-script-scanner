from __future__ import annotations
import pandas as pd

def candles_to_frame(payload: dict) -> pd.DataFrame:
    """Normalize an Upstox candle payload into the engine's OHLCV schema.

    Expected candle rows are [timestamp, open, high, low, close, volume, oi].
    The adapter deliberately keeps broker-specific parsing here so the engine
    remains broker-neutral.
    """
    candles = payload.get("data", {}).get("candles", [])
    rows = []
    for c in candles:
        if len(c) < 6:
            continue
        rows.append({
            "timestamp": c[0],
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
        })
    if not rows:
        return pd.DataFrame(columns=["timestamp","open","high","low","close","volume"])
    out = pd.DataFrame(rows)
    out["timestamp"] = pd.to_datetime(out["timestamp"])
    return out.sort_values("timestamp").reset_index(drop=True)
