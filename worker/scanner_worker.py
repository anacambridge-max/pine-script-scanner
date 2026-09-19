from __future__ import annotations

import os
import signal
from typing import Any

import pandas as pd

from engine import PrimeConfig, PrimeEngine
from worker.signal_store import DailySignalStore
from worker.upstox_feed import UpstoxV3Feed


def parse_instruments() -> list[str]:
    raw = os.getenv("UPSTOX_INSTRUMENT_KEYS", "")
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    if not keys:
        raise RuntimeError(
            "UPSTOX_INSTRUMENT_KEYS is required, e.g. "
            "NSE_EQ|INE002A01018,NSE_EQ|INE020B01018"
        )
    return keys


class ScannerWorker:
    def __init__(self):
        token = os.getenv("UPSTOX_ACCESS_TOKEN")
        if not token:
            raise RuntimeError("UPSTOX_ACCESS_TOKEN is required")

        self.engine = PrimeEngine(PrimeConfig())
        self.store = DailySignalStore()
        self.feed = UpstoxV3Feed(token, parse_instruments())
        self.feed.on_bar(self._on_bar)
        self.running = True

    @staticmethod
    def _aggregate_ohlcv(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
        x = df.copy().set_index("timestamp")
        out = x.resample(
            f"{minutes}min", origin="start_day", offset="15min"
        ).agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        ).dropna().reset_index()
        return out

    def _on_bar(self, instrument_key: str, one_minute: pd.DataFrame) -> None:
        # The WebSocket is the live layer. Historical seeding is the next
        # improvement so the engine has enough context immediately after start.
        one_minute = one_minute.tail(6000)

        for timeframe in (1, 3, 5):
            frame = one_minute if timeframe == 1 else self._aggregate_ohlcv(one_minute, timeframe)
            if len(frame) < 30:
                continue

            result: dict[str, Any] = self.engine.evaluate(frame, timeframe, context=context)
            result["symbol"] = instrument_key

            if result.get("state") == "CONFIRMED" and result.get("direction") in {"BUY", "SELL"}:
                if self.store.add_confirmed(result):
                    print(
                        f"[CONFIRMED] {result['direction']} {instrument_key} "
                        f"{timeframe}m score={result.get('prime_score')} "
                        f"time={result.get('timestamp')}"
                    )

    def stop(self, *_args: Any) -> None:
        self.running = False
        try:
            self.feed.streamer.disconnect()
        except Exception:
            pass

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        print("Prime live scanner starting...")
        self.feed.connect()


if __name__ == "__main__":
    ScannerWorker().run()
