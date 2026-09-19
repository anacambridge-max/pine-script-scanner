from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd
import requests


class UpstoxV3Feed:
    """Upstox V3 full-feed adapter with one-minute OHLC normalization."""

    def __init__(self, access_token: str, instrument_keys: list[str]):
        try:
            import upstox_client
        except ImportError as exc:
            raise RuntimeError("Install upstox-python-sdk before starting the live worker") from exc

        self._sdk = upstox_client
        self.access_token = access_token
        self.instrument_keys = list(instrument_keys)
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

    def seed_history(self) -> None:
        """Seed up to one month of 1-minute candles before opening the live stream."""
        to_date = date.today()
        from_date = to_date - timedelta(days=30)
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

        for index, instrument_key in enumerate(self.instrument_keys):
            encoded = requests.utils.quote(instrument_key, safe="")
            url = (
                f"https://api.upstox.com/v3/historical-candle/{encoded}/minutes/1/"
                f"{to_date.isoformat()}/{from_date.isoformat()}"
            )
            try:
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                candles = response.json().get("data", {}).get("candles", [])
                for c in candles:
                    if len(c) < 6:
                        continue
                    ts = pd.to_datetime(c[0]).tz_convert("Asia/Kolkata")
                    self._bars[instrument_key][ts] = {
                        "timestamp": ts,
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    }
                if (index + 1) % 25 == 0:
                    print(f"Historical seed: {index + 1}/{len(instrument_keys)}")
            except Exception as exc:
                print(f"Historical seed failed for {instrument_key}: {exc}")

    def connect(self) -> None:
        self.streamer.connect()
