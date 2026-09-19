from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Callable

import pandas as pd


class UpstoxV3Feed:
    """Thin adapter around the official Upstox MarketDataStreamerV3 SDK.

    The Upstox V3 full feed provides the live I1 (1-minute) OHLC candle.
    We normalize that candle here; the scanner remains broker-neutral.
    """

    def __init__(self, access_token: str, instrument_keys: list[str]):
        try:
            import upstox_client
        except ImportError as exc:
            raise RuntimeError("Install upstox-python-sdk before starting the live worker") from exc

        self._sdk = upstox_client
        cfg = upstox_client.Configuration()
        cfg.access_token = access_token
        self.streamer = upstox_client.MarketDataStreamerV3(
            upstox_client.ApiClient(cfg), instrument_keys, "full"
        )
        self._callbacks: list[Callable[[str, pd.DataFrame], None]] = []
        self._bars: dict[str, dict[pd.Timestamp, dict[str, float]]] = defaultdict(dict)

        self.streamer.on("open", self._on_open)
        self.streamer.on("message", self._on_message)
        self.streamer.on("error", self._on_error)
        self.streamer.on("close", self._on_close)

    def on_bar(self, callback: Callable[[str, pd.DataFrame], None]) -> None:
        self._callbacks.append(callback)

    def _on_open(self, *_args: Any) -> None:
        print("Upstox V3 WebSocket connected")

    def _on_error(self, error: Any) -> None:
        print(f"Upstox WebSocket error: {error}")

    def _on_close(self, *_args: Any) -> None:
        print("Upstox V3 WebSocket closed")

    @staticmethod
    def _find_market_ff(feed: dict[str, Any]) -> dict[str, Any] | None:
        full = feed.get("fullFeed") or feed.get("ff") or feed.get("full_feed")
        if not full:
            return None
        return full.get("marketFF") or full.get("market_ff")

    def _on_message(self, message: dict[str, Any]) -> None:
        for instrument_key, feed in (message.get("feeds") or {}).items():
            market_ff = self._find_market_ff(feed)
            if not market_ff:
                continue

            ohlc = (market_ff.get("marketOHLC") or {}).get("ohlc") or []
            candle = next((c for c in ohlc if c.get("interval") == "I1"), None)
            if not candle:
                continue

            ts = pd.to_datetime(int(candle["ts"]), unit="ms", utc=True).tz_convert("Asia/Kolkata")
            self._bars[instrument_key][ts] = {
                "timestamp": ts,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle.get("vol", 0)),
            }

            frame = pd.DataFrame(list(self._bars[instrument_key].values()))
            frame = frame.sort_values("timestamp").reset_index(drop=True)
            for callback in self._callbacks:
                callback(instrument_key, frame)

    def connect(self) -> None:
        self.streamer.connect()
