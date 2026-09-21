from __future__ import annotations

import os
import signal
import threading
import time
import traceback
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

        self.access_token = token
        self.engine = PrimeEngine(PrimeConfig())
        self.supabase = SupabaseStore()
        self.instruments = load_fno_stock_instruments()
        self.instrument_map = {
            x["instrument_key"]: x.get("trading_symbol") or x["instrument_key"].split("|", 1)[-1]
            for x in self.instruments
        }
        self.company_map = {
            x["instrument_key"]: x.get("company_name") or x.get("trading_symbol") or x["instrument_key"].split("|", 1)[-1]
            for x in self.instruments
        }
        self.feed = self._new_feed()
        self.running = True
        self.captured_count = 0
        self.last_heartbeat = 0.0
        self._heartbeat_thread: threading.Thread | None = None

    def _new_feed(self) -> UpstoxV3Feed:
        feed = UpstoxV3Feed(self.access_token, list(self.instrument_map))
        feed.on_bar(self._on_bar)
        return feed

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

    @staticmethod
    def _timeframe_bar_is_closed(completed_1m_ts: pd.Timestamp, timeframe: int) -> bool:
        # NSE session anchored at 09:15:
        # 3m bars close at :17, :20, :23...
        # 5m bars close at :19, :24, :29...
        minutes_from_anchor = (
            completed_1m_ts.hour * 60
            + completed_1m_ts.minute
            - (9 * 60 + 15)
        )
        return (
            minutes_from_anchor >= 0
            and (minutes_from_anchor + 1) % timeframe == 0
        )

    def _heartbeat(self, status: str = "LIVE", error: str | None = None) -> None:
        now = time.time()
        if now - self.last_heartbeat < 25 and status == "LIVE":
            return
        self.last_heartbeat = now
        try:
            self.supabase.heartbeat(
                status,
                len(self.instrument_map),
                self.captured_count,
                error,
            )
        except Exception as exc:
            print(f"[HEARTBEAT ERROR] {exc}")

    def _heartbeat_loop(self) -> None:
        while self.running:
            self._heartbeat("LIVE")
            for _ in range(30):
                if not self.running:
                    return
                time.sleep(1)

    def _on_bar(self, instrument_key: str, one_minute: pd.DataFrame) -> None:
        one_minute = one_minute.tail(6000)
        symbol = self.instrument_map.get(instrument_key, instrument_key)
        if one_minute.empty:
            return

        completed_1m_ts = pd.to_datetime(one_minute["timestamp"].iloc[-1])

        for timeframe in (3,):
            if timeframe != 1 and not self._timeframe_bar_is_closed(
                completed_1m_ts, timeframe
            ):
                continue

            frame = (
                one_minute
                if timeframe == 1
                else self._aggregate_ohlcv(one_minute, timeframe)
            )
            if len(frame) < 30:
                continue

            try:
                result: dict[str, Any] = self.engine.evaluate(
                    frame, timeframe, context=None
                )
            except Exception as exc:
                self._heartbeat("ERROR", str(exc))
                print(f"[ENGINE ERROR] {symbol} {timeframe}m: {exc!r}")
                traceback.print_exc()
                continue

            if (
                result.get("state") == "CONFIRMED"
                and result.get("direction") in {"BUY", "SELL"}
            ):
                try:
                    company_name = self.company_map.get(instrument_key, symbol)
                    inserted = self.supabase.write_signal(
                        result, instrument_key, symbol, company_name
                    )
                    if inserted:
                        send_confirmed({**result, "symbol": symbol, "company_name": company_name})
                        self.captured_count += 1
                        print(
                            f"[CONFIRMED] {result['direction']} {symbol} "
                            f"{timeframe}m score={result.get('prime_score')} "
                            f"time={result.get('timestamp')}"
                        )
                except Exception as exc:
                    self._heartbeat("ERROR", str(exc))
                    print(f"[PERSIST ERROR] {symbol}: {exc}")

        self._heartbeat("LIVE")

    def stop(self, *_args: Any) -> None:
        self.running = False
        try:
            self.feed.streamer.disconnect()
        except Exception:
            pass

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        self._heartbeat("STARTING")
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="scanner-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

        print(
            f"Prime live scanner starting with {len(self.instrument_map)} "
            "F&O stock underlyings — 3m PDH/PDL + 2x volume mode..."
        )
        print("Seeding one month of 1-minute history...")
        self.feed.seed_history()
        self._heartbeat("HISTORY_READY")

        reconnect_delay = 20

        while self.running:
            try:
                print("Connecting to Upstox V3 WebSocket...")
                self.feed.connect()
                # connect() starts the SDK's websocket thread and returns
                # immediately. Wait for its actual close event before creating
                # another streamer; rebuilding immediately causes overlapping
                # handshakes and Upstox 403 responses.
                self.feed.wait_until_closed()

                if self.running:
                    print(
                        f"Upstox connection closed; waiting {reconnect_delay}s "
                        "before rebuilding connection..."
                    )
                    self._heartbeat("RECONNECTING")
                    time.sleep(reconnect_delay)
                    self.feed = self._new_feed()
                    reconnect_delay = min(reconnect_delay + 10, 60)

            except Exception as exc:
                self._heartbeat("RECONNECTING", str(exc))
                print(
                    f"[FEED ERROR] {exc}; waiting {reconnect_delay}s "
                    "before rebuilding..."
                )
                time.sleep(reconnect_delay)
                if self.running:
                    self.feed = self._new_feed()
                reconnect_delay = min(reconnect_delay + 10, 60)


if __name__ == "__main__":
    ScannerWorker().run()
