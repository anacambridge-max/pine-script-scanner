from __future__ import annotations

import os
import signal
import time
from typing import Any

import pandas as pd

from engine import PrimeConfig, PrimeEngine
from worker.instruments import load_fno_stock_instruments
from worker.supabase_store import SupabaseStore
from worker.telegram import send_confirmed
from worker.upstox_feed import UpstoxV3Feed


class ScannerWorker:
    def __init__(self):
        token = os.getenv("UPSTOX_ACCESS_TOKEN")
        if not token:
            raise RuntimeError("UPSTOX_ACCESS_TOKEN is required")

        self.engine = PrimeEngine(PrimeConfig())
        self.supabase = SupabaseStore()
        self.instruments = load_fno_stock_instruments()
        self.instrument_map = {
            x["instrument_key"]: x.get("trading_symbol") or x["instrument_key"].split("|", 1)[-1]
            for x in self.instruments
        }
        self.feed = UpstoxV3Feed(token, list(self.instrument_map))
        self.feed.on_bar(self._on_bar)
        self.running = True
        self.captured_count = 0
        self.last_heartbeat = 0.0

    @staticmethod
    def _aggregate_ohlcv(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
        x = df.copy().set_index("timestamp")
        return (
            x.resample(f"{minutes}min", origin="start_day", offset="15min")
            .agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
            )
            .dropna()
            .reset_index()
        )

    def _heartbeat(self, status: str = "RUNNING", error: str | None = None) -> None:
        now = time.time()
        if now - self.last_heartbeat < 30 and status == "RUNNING":
            return
        self.last_heartbeat = now
        try:
            self.supabase.heartbeat(status, len(self.instrument_map), self.captured_count, error)
        except Exception as exc:
            print(f"[HEARTBEAT ERROR] {exc}")

    def _on_bar(self, instrument_key: str, one_minute: pd.DataFrame) -> None:
        one_minute = one_minute.tail(6000)
        symbol = self.instrument_map.get(instrument_key, instrument_key)

        for timeframe in (1, 3, 5):
            frame = one_minute if timeframe == 1 else self._aggregate_ohlcv(one_minute, timeframe)
            if len(frame) < 30:
                continue
            try:
                result: dict[str, Any] = self.engine.evaluate(frame, timeframe, context=None)
            except Exception as exc:
                self._heartbeat("ERROR", str(exc))
                print(f"[ENGINE ERROR] {symbol} {timeframe}m: {exc}")
                continue

            if result.get("state") == "CONFIRMED" and result.get("direction") in {"BUY", "SELL"}:
                try:
                    inserted = self.supabase.write_signal(result, instrument_key, symbol)
                    if inserted:
                        send_confirmed({**result, "symbol": symbol})
                        self.captured_count += 1
                    print(
                        f"[CONFIRMED] {result['direction']} {symbol} "
                        f"{timeframe}m score={result.get('prime_score')} "
                        f"time={result.get('timestamp')}"
                    )
                except Exception as exc:
                    self._heartbeat("ERROR", str(exc))
                    print(f"[PERSIST ERROR] {symbol}: {exc}")

        self._heartbeat()

    def stop(self, *_args: Any) -> None:
        self.running = False
        try:
            self.feed.streamer.disconnect()
        except Exception:
            pass

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)
        print(f"Prime live scanner starting with {len(self.instrument_map)} F&O stock underlyings...")
        self._heartbeat("STARTING")
        print("Seeding one month of 1-minute history...")
        self.feed.seed_history()
        self._heartbeat("HISTORY_READY")
        while self.running:
            try:
                self.feed.connect()
                break
            except Exception as exc:
                self._heartbeat("RECONNECTING", str(exc))
                print(f"[FEED ERROR] {exc}; retrying in 10s")
                time.sleep(10)


if __name__ == "__main__":
    ScannerWorker().run()
