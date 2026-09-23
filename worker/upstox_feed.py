from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Callable
import time
import threading

import pandas as pd
import requests


class UpstoxV3Feed:
    """Upstox V3 full-feed adapter with lightweight completed 1-minute candle emission."""

    def __init__(self, access_token: str, instrument_keys: list[str]):
        try:
            import upstox_client
        except ImportError as exc:
            raise RuntimeError("Install upstox-python-sdk before starting the live worker") from exc

        self._sdk = upstox_client
        self.access_token = access_token
        self.instrument_keys = list(instrument_keys)
        self._callbacks: list[Callable[[str, pd.DataFrame], None]] = []
        self._bars: dict[str, dict[pd.Timestamp, dict[str, float]]] = defaultdict(dict)

        self._live_started: set[str] = set()
        self._last_live_ts: dict[str, pd.Timestamp] = {}
        self._last_emitted_ts: dict[str, pd.Timestamp] = {}
        self._message_count = 0
        self._last_message_log = 0.0
        self._closed = threading.Event()

        self.streamer = self._build_streamer()

    def _build_streamer(self):
        cfg = self._sdk.Configuration()
        cfg.access_token = self.access_token
        # Follow Upstox's documented V3 pattern: create the streamer first
        # and explicitly subscribe inside the open callback. This guarantees
        # the post-authentication subscription request is actually sent.
        streamer = self._sdk.MarketDataStreamerV3(
            self._sdk.ApiClient(cfg), [], "full"
        )

        # Keep reconnect ownership in ScannerWorker. The SDK's internal
        # reconnect thread can overlap with our worker-level rebuilds and
        # create multiple concurrent websocket handshakes. Upstox currently
        # allows only 2 normal websocket connections per user.
        streamer.auto_reconnect(False)

        streamer.on("open", self._on_open)
        streamer.on("message", self._on_message)
        streamer.on("error", self._on_error)
        streamer.on("close", self._on_close)
        return streamer

    def rebuild_streamer(self) -> None:
        try:
            self.streamer.disconnect()
        except Exception:
            pass
        self.streamer = self._build_streamer()

    def on_bar(self, callback: Callable[[str, pd.DataFrame], None]) -> None:
        self._callbacks.append(callback)

    def _on_open(self, *_args: Any) -> None:
        self._closed.clear()
        print(
            f"Upstox V3 WebSocket connected; subscribing "
            f"{len(self.instrument_keys)} instruments..."
        )
        try:
            self.streamer.subscribe(self.instrument_keys, "full")
            print(f"Upstox V3 subscription sent: {len(self.instrument_keys)} instruments")
        except Exception as exc:
            print(f"Upstox V3 subscription error: {exc}")
            try:
                self.streamer.disconnect()
            except Exception:
                pass

    def _on_error(self, error: Any) -> None:
        print(f"Upstox V3 WebSocket error: {error}")

    def _on_close(self, *_args: Any) -> None:
        self._closed.set()
        print("Upstox V3 WebSocket closed")

    @staticmethod
    def _find_market_ff(feed: dict[str, Any]) -> dict[str, Any] | None:
        full = feed.get("fullFeed") or feed.get("ff") or feed.get("full_feed")
        if not full:
            return None
        return full.get("marketFF") or full.get("market_ff")

    @staticmethod
    def _extract_latest_i1(market_ff: dict[str, Any]) -> dict[str, Any] | None:
        ohlc = (market_ff.get("marketOHLC") or {}).get("ohlc") or []
        candles = [
            c for c in ohlc
            if c.get("interval") == "I1" and c.get("ts") is not None
        ]
        if not candles:
            return None
        # Upstox can send both current and previous I1 candles. Select by ts,
        # never by array position.
        return max(candles, key=lambda c: int(c["ts"]))

    def _on_message(self, message: dict[str, Any]) -> None:
        self._message_count += 1

        for instrument_key, feed in (message.get("feeds") or {}).items():
            market_ff = self._find_market_ff(feed)
            if not market_ff:
                continue

            candle = self._extract_latest_i1(market_ff)
            if not candle:
                continue

            ts = pd.to_datetime(
                int(candle["ts"]), unit="ms", utc=True
            ).tz_convert("Asia/Kolkata")

            self._bars[instrument_key][ts] = {
                "timestamp": ts,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle.get("vol", candle.get("volume", 0))),
            }

            # The first live snapshot establishes the current candle. Do not
            # emit the previous session's last candle as a new live bar.
            if instrument_key not in self._live_started:
                self._live_started.add(instrument_key)
                self._last_live_ts[instrument_key] = ts
                self._last_emitted_ts[instrument_key] = max(
                    (x for x in self._bars[instrument_key] if x < ts),
                    default=ts,
                )
                continue

            previous_live_ts = self._last_live_ts[instrument_key]
            if ts <= previous_live_ts:
                continue

            # A new minute is now visible, so the preceding minute is closed.
            # Emit each newly completed candle once. Heavy Pandas/engine work
            # therefore runs at most once per instrument per minute, not once
            # per websocket tick.
            completed = sorted(
                x for x in self._bars[instrument_key]
                if self._last_emitted_ts[instrument_key] < x < ts
            )

            for completed_ts in completed:
                frame = pd.DataFrame(
                    [
                        row
                        for row_ts, row in self._bars[instrument_key].items()
                        if row_ts <= completed_ts
                    ]
                ).sort_values("timestamp").reset_index(drop=True)

                for callback in self._callbacks:
                    callback(instrument_key, frame)

                self._last_emitted_ts[instrument_key] = completed_ts

            self._last_live_ts[instrument_key] = ts

        # Print a compact feed-health line every 30 seconds instead of dumping
        # every websocket message to the terminal.
        now = time.time()
        if now - self._last_message_log >= 30:
            self._last_message_log = now
            print(
                f"[FEED] messages={self._message_count} "
                f"instruments_with_data={len(self._live_started)}"
            )

    def seed_history(self) -> None:
        """Seed up to 60 calendar days of 1-minute candles before opening the live stream."""
        to_date = date.today()
        from_date = to_date - timedelta(days=60)
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
                    ts = pd.to_datetime(c[0], utc=True).tz_convert("Asia/Kolkata")
                    self._bars[instrument_key][ts] = {
                        "timestamp": ts,
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5]),
                    }
                if (index + 1) % 25 == 0:
                    print(f"Historical seed: {index + 1}/{len(self.instrument_keys)}")
            except Exception as exc:
                print(f"Historical seed failed for {instrument_key}: {exc}")

    def get_histories(self) -> dict[str, pd.DataFrame]:
        """Return a snapshot of seeded/live 1-minute histories for analysis."""
        return {
            key: pd.DataFrame(list(rows.values())).sort_values("timestamp").reset_index(drop=True)
            for key, rows in self._bars.items()
            if rows
        }

    def connect(self) -> None:
        self._closed.clear()
        self.streamer.connect()

    def wait_until_closed(self, timeout: float = 3600) -> bool:
        """Wait while the SDK owns the active websocket connection."""
        return self._closed.wait(timeout)
