from __future__ import annotations

import os
import json
import signal
import threading
import time
import traceback
from typing import Any

import pandas as pd

from engine import PrimeConfig, PrimeEngine
from worker.instruments import load_fno_stock_instruments
from worker.next_day_scanner import NextDayScanner
from worker.morning_hot_scanner import MorningHotScanner
from worker.moneycontrol_news import fetch_moneycontrol_news
from worker.supabase_store import SupabaseStore
from worker.sector_ranker import SectorRanker
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
        self.sector_ranker = SectorRanker()
        self.next_day_scanner = NextDayScanner(top_n=3)
        self.morning_hot_scanner = MorningHotScanner(top_n=5)
        self._morning_hot_done: set[str] = set()
        self._premarket_snapshot_minute: str | None = None
        self._next_day_thread: threading.Thread | None = None
        self._next_day_done: set[str] = set()
        self._daily_history_cache: dict[str, dict[str, pd.DataFrame]] = {}
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
            try:
                self._run_nse_premarket_study()
            except Exception as exc:
                print(f"[NSE PRE-MARKET WARNING] {exc}")
            for _ in range(30):
                if not self.running:
                    return
                time.sleep(1)

    def _morning_hot_loop(self) -> None:
        # Retry during pre-open even when the worker starts before 09:00.
        # A one-shot startup call can miss the valid news window entirely.
        while self.running:
            try:
                self._run_morning_hot_scan()
            except Exception as exc:
                print(f"[MORNING LOOP WARNING] {exc}")
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
                # Evaluate the trading signal FIRST. Sector data is optional
                # scoring context and must never block or delay the live scanner.
                result: dict[str, Any] = self.engine.evaluate(
                    frame, timeframe, context=None
                )

                # Only fetch sector data after a real confirmed signal exists.
                # This prevents NSE API latency/errors from delaying evaluation
                # of the 210-stock universe.
                if (
                    result.get("state") == "CONFIRMED"
                    and result.get("direction") in {"BUY", "SELL"}
                ):
                    try:
                        sector_context = self.sector_ranker.get(
                            symbol, result.get("direction", "")
                        )
                        result = self.engine.evaluate(
                            frame, timeframe, context=sector_context
                        )
                        result.update(sector_context)
                        result["sector_change_percent"] = sector_context.get("sector_change")
                        result["sector_rank_type"] = (result.get("score_breakdown") or {}).get("sector_rank_type")
                        result["sector_bonus"] = (result.get("score_breakdown") or {}).get("sector_bonus", 0)
                    except Exception as sector_exc:
                        print(f"[SECTOR WARNING] {symbol}: {sector_exc}")
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

    @staticmethod
    def _next_business_day(analysis_date: pd.Timestamp) -> str:
        target = analysis_date.date() + pd.Timedelta(days=1)
        while target.weekday() >= 5:
            target += pd.Timedelta(days=1)
        return target.isoformat()


    def _run_nse_premarket_study(self) -> None:
        now = pd.Timestamp.now(tz="Asia/Kolkata")
        if now.weekday() >= 5 or not (now.hour == 9 and 0 <= now.minute <= 8):
            return
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if minute_key == self._premarket_snapshot_minute:
            return
        from worker.nse_premarket import NSEPreMarketStudy
        snapshot = NSEPreMarketStudy().collect(now.to_pydatetime())
        if snapshot.get("status") != "ok":
            print(f"[NSE PRE-MARKET] {minute_key}: {snapshot.get('status')} {snapshot.get('error', '')}")
            return
        rows = snapshot.get("rows", [])
        payload = [{
            "id": f"{snapshot['snapshot_time']}|{row['symbol']}",
            "snapshot_time": snapshot["snapshot_time"],
            "trade_date": now.date().isoformat(),
            "symbol": row["symbol"],
            "previous_close": row.get("previous_close"),
            "indicative_price": row.get("indicative_price"),
            "indicative_gap_pct": row.get("indicative_gap_pct"),
            "indicative_tradable_qty": row.get("indicative_tradable_qty"),
            "buy_qty": row.get("buy_qty"),
            "sell_qty": row.get("sell_qty"),
            "imbalance_qty": row.get("imbalance_qty"),
            "oi_change_pct": row.get("oi_change_pct"),
            "oi_volume": row.get("oi_volume"),
            "preopen_score": row.get("preopen_score", 0),
            "preopen_bias": row.get("preopen_bias", "NEUTRAL / MIXED"),
            "reasons": row.get("reasons", []),
            "source_preopen": row.get("source_preopen"),
            "source_oi": row.get("source_oi"),
        } for row in rows]
        if not payload:
            print(f"[NSE PRE-MARKET] {minute_key}: no usable pre-open rows; will retry next minute")
            return
        self.supabase._request(
            "POST", "nse_premarket_study",
            params={"on_conflict": "id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            data=json.dumps(payload, default=str),
        )
        self._premarket_snapshot_minute = minute_key
        print(f"[NSE PRE-MARKET] {snapshot['snapshot_time']}: preopen={snapshot.get('preopen_count', 0)} OI={snapshot.get('oi_count', 0)} stored={len(rows)}")

    def _run_morning_hot_scan(self) -> None:
        try:
            now = pd.Timestamp.now(tz="Asia/Kolkata")
            trade_date = now.date().isoformat()
            if trade_date in self._morning_hot_done:
                return
            from worker.hot_stocks_config import PREOPEN_CUTOFF, SCAN_CUTOFF, NSE_HOLIDAYS
            current_clock = now.time().replace(tzinfo=None)
            if current_clock < PREOPEN_CUTOFF or current_clock >= SCAN_CUTOFF:
                return

            today = now.date()
            if today.weekday() >= 5 or today.isoformat() in NSE_HOLIDAYS:
                self._morning_hot_done.add(trade_date)
                print(f"[MORNING] Skipping non-trading day {trade_date}")
                return

            # Capture the Moneycontrol snapshot immediately, while we are still
            # inside the pre-open window. This prevents later 09:15+ headlines
            # from leaking into a morning scan if the data fetch takes time.
            print(f"[MORNING] Fetching Moneycontrol catalysts for {today.isoformat()}...")
            news_items = fetch_moneycontrol_news(max_items=40)
            print(f"[MORNING] Moneycontrol headlines loaded: {len(news_items)}")

            # Use compact daily candles for the pre-open technical scan. The
            # heavy 1-minute seed is reserved for the live 3M engine.
            histories = self.feed.get_daily_histories(lookback_days=60)
            available_dates: list[Any] = []
            for frame in histories.values():
                if frame.empty:
                    continue
                ts = pd.to_datetime(frame["timestamp"])
                dates = ts.dt.date
                valid = dates[dates < today]
                if not valid.empty:
                    available_dates.extend(valid.tolist())
            if not available_dates:
                print("[MORNING] No completed session available yet; will retry on next startup/cycle")
                return

            session_dates = sorted(set(available_dates))
            analysis_date = session_dates[-1]
            previous_session_date = session_dates[-2] if len(session_dates) > 1 else None
            rows, technical_only = self.morning_hot_scanner.scan_all(
                histories, self.instrument_map, self.company_map, analysis_date, news_items,
                scan_time=now.to_pydatetime(),
            )
            # Replace the whole daily snapshot, not just upsert returned rows.
            # Otherwise an empty scan can leave yesterday's candidates visible.
            self.supabase._request(
                "DELETE", "morning_hot_stocks",
                params={"trade_date": f"eq.{analysis_date.isoformat()}"},
            )
            from worker.hot_stocks_store import clear_technical_watch, write_technical_watch
            clear_technical_watch(self.supabase, analysis_date.isoformat())
            count = self.supabase.write_morning_hot_stocks(rows)
            technical_count = write_technical_watch(self.supabase, technical_only)
            # Persist local history even when Supabase has no qualified hot names.
            try:
                from worker.hot_stocks_history import HotStockHistory
                history = HotStockHistory()
                if previous_session_date is not None:
                    next_session_prices: dict[str, dict[str, float]] = {}
                    for instrument_key, frame in histories.items():
                        if frame.empty:
                            continue
                        frame_dates = pd.to_datetime(frame["timestamp"]).dt.date
                        day = frame.loc[frame_dates == analysis_date]
                        if day.empty:
                            continue
                        symbol = self.instrument_map.get(instrument_key, instrument_key.split("|", 1)[-1])
                        next_session_prices[symbol] = {
                            "close": float(day["close"].iloc[-1]),
                            "high": float(day["high"].max()),
                            "low": float(day["low"].min()),
                        }
                    updated_outcomes = history.update_next_session_outcomes(
                        previous_session_date.isoformat(), next_session_prices
                    )
                    if updated_outcomes:
                        print(f"[MORNING BACKTEST] Updated {updated_outcomes} prior-session outcomes")
                history.save(rows, analysis_date.isoformat(), "HOT")
                history.save(technical_only, analysis_date.isoformat(), "TECHNICAL_ONLY")
                history.export_csv()
                backtest = history.backtest(min_move_pct=1.5)
                print(
                    f"[MORNING BACKTEST] evaluated={backtest['evaluated']} "
                    f"move_hits={backtest['absolute_move_hits']} "
                    f"range_hits={backtest['range_expansion_hits']}"
                )
            except Exception as history_exc:
                print(f"[MORNING HISTORY WARNING] {history_exc}")
            if count or technical_count or not rows:
                self._morning_hot_done.add(trade_date)
            print(
                f"[MORNING] {today.isoformat()}: hot={count}, technical-only={technical_count}; "
                f"completed session={analysis_date.isoformat()}, news items={len(news_items)}"
            )
            for row in rows:
                print(f"[MORNING HOT] {row['symbol']} score={row['score']} tech={row['technical_score']} "
                      f"news={row['news_score']} source={row.get('news_source')} published={row.get('published_ist')}")
            for row in technical_only:
                print(f"[MORNING TECH WATCH] {row['symbol']} tech={row['technical_score']}")
        except Exception as exc:
            print(f"[MORNING ERROR] {exc}")
            traceback.print_exc()

    def _run_next_day_scan(self, analysis_date: pd.Timestamp) -> None:
        try:
            cutoff = analysis_date.date()
            cache_key = cutoff.isoformat()
            histories = self._daily_history_cache.get(cache_key)
            if histories is None:
                histories = self.feed.get_daily_histories(
                    lookback_days=60,
                    to_date=cutoff,
                )
                self._daily_history_cache[cache_key] = histories
            available_dates = []
            for frame in histories.values():
                if frame.empty:
                    continue
                ts = pd.to_datetime(frame["timestamp"])
                dates = ts.dt.date
                valid = dates[dates <= cutoff]
                if not valid.empty:
                    available_dates.append(valid.max())
            if not available_dates:
                return

            actual_date = max(available_dates)

            # Never silently fall back to an older session. If we are building
            # today's watchlist before the close, the required D-1 session is
            # yesterday. If that completed session is not present in history
            # yet, wait and retry on the next loop.
            if actual_date != cutoff:
                print(
                    f"[D-1] waiting for completed session {cutoff}; "
                    f"latest available session is {actual_date}"
                )
                return

            key = actual_date.isoformat()
            if key in self._next_day_done:
                return

            rows = self.next_day_scanner.scan(
                histories,
                self.instrument_map,
                self.company_map,
                actual_date,
            )
            target_date = self._next_business_day(pd.Timestamp(actual_date))
            for row in rows:
                row["target_date"] = target_date
            instrument_lookup = {
                symbol: instrument_key
                for instrument_key, symbol in self.instrument_map.items()
            }
            count = self.supabase.write_next_day_watchlist(rows, instrument_lookup)
            if count == 0:
                print(
                    f"[D-1] {key}: no qualifying candidates yet; "
                    "will retry on the next cycle"
                )
                return
            self._next_day_done.add(key)
            print(
                f"[D-1] {key} -> {target_date}: "
                f"{count} candidates stored "
                f"(BUY={sum(1 for x in rows if x['direction']=='BUY')}, "
                f"SELL={sum(1 for x in rows if x['direction']=='SELL')})"
            )
            for row in rows:
                print(
                    f"[D-1] {row['direction']} {row['symbol']} "
                    f"score={row['score']} grade={row['grade']} "
                    f"reasons={', '.join(row['reasons'])}"
                )
        except Exception as exc:
            print(f"[D-1 ERROR] {exc}")
            traceback.print_exc()

    def _next_day_loop(self) -> None:
        refreshed_today = False

        while self.running:
            try:
                now = pd.Timestamp.now(tz="Asia/Kolkata")
                after_close = now.hour > 15 or (now.hour == 15 and now.minute >= 35)

                if not after_close:
                    analysis_date = now.normalize() - pd.Timedelta(days=1)
                else:
                    analysis_date = now.normalize()

                    # After 15:35, do one authoritative Upstox V3 intraday
                    # refresh for today's complete session. This avoids relying
                    # on the websocket's final post-close update and guarantees
                    # the D-1 scan uses today's completed candles.
                    if not refreshed_today:
                        print("[D-1] Market close reached; daily history will include today's completed session.")
                        # The D-1 scanner now uses Upstox V3 daily candles directly.
                        # No heavy 1-minute refresh is needed here.
                        refreshed_today = True

                self._run_next_day_scan(analysis_date)
            except Exception as exc:
                print(f"[D-1 LOOP ERROR] {exc}")
            for _ in range(60):
                if not self.running:
                    return
                time.sleep(1)

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
        try:
            deleted = self.supabase.delete_previous_days()
            if deleted:
                print(f"[CLEANUP] Removed {deleted} previous-day scanner signals")
        except Exception as exc:
            print(f"[CLEANUP ERROR] {exc}")
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
        # Retry the morning scan independently so startup before 09:00 does
        # not miss the fresh-news window or block the NSE snapshot collector.
        threading.Thread(
            target=self._morning_hot_loop,
            name="morning-hot-scan",
            daemon=True,
        ).start()

        # Live 3M PDH/PDL + volume logic only needs the previous trading
        # session and the current session. Do not block the opening scan with
        # a 60-day minute-history bootstrap.
        print("Seeding 3 calendar days of 1-minute history for the live 3M engine...")
        self.feed.seed_history(days=3)
        self._heartbeat("HISTORY_READY")

        # Start D-1 analysis only after the full minute-history seed is ready.
        self._next_day_thread = threading.Thread(
            target=self._next_day_loop,
            name="next-day-scanner",
            daemon=True,
        )
        self._next_day_thread.start()

        # Backfill sector/rank for today's existing signals so rows created
        # before the sector-ranker fix also become enriched.
        try:
            existing_signals = self.supabase.get_today_confirmed_signals()
            if existing_signals:
                print(f"[SECTOR] Backfilling {len(existing_signals)} today's confirmed signals...")
                for signal_row in existing_signals:
                    try:
                        symbol = str(signal_row.get("symbol") or "")
                        direction = str(signal_row.get("signal_type") or "")
                        context = self.sector_ranker.get(symbol, direction)
                        metadata = dict(signal_row.get("metadata") or {})
                        metadata.update({
                            "sector": context.get("sector"),
                            "sector_change_percent": context.get("sector_change"),
                            "sector_rank": context.get("sector_rank"),
                            "sector_rank_type": context.get("sector_rank_type"),
                        })
                        raw_breakdown = signal_row.get("score_breakdown")
                        breakdown = dict(raw_breakdown) if isinstance(raw_breakdown, dict) else {}
                        sector_bonus = float(context.get("sector_bonus") or 0)
                        old_sector_bonus = float(breakdown.get("sector_bonus") or 0)
                        current_score = int(signal_row.get("score") or 0)
                        new_score = max(0, min(100, round(current_score - old_sector_bonus + sector_bonus)))
                        new_grade = (
                            "PRIME A+" if new_score >= 90
                            else "PRIME A" if new_score >= 80
                            else "STRONG" if new_score >= 70
                            else "GOOD" if new_score >= 60
                            else "WATCH" if new_score >= 50
                            else "WEAK"
                        )
                        breakdown.update({
                            "sector": context.get("sector"),
                            "sector_change_percent": context.get("sector_change"),
                            "sector_rank": context.get("sector_rank"),
                            "sector_rank_type": context.get("sector_rank_type"),
                            "sector_bonus": sector_bonus,
                            "total": new_score,
                        })
                        self.supabase.update_signal_sector(
                            str(signal_row.get("id")),
                            metadata,
                            score_breakdown=breakdown,
                            score=new_score,
                            grade=new_grade,
                        )
                        print(
                            f"[SECTOR] {symbol}: "
                            f"{context.get('sector')} rank={context.get('sector_rank')} "
                            f"change={context.get('sector_change')}"
                        )
                    except Exception as exc:
                        print(f"[SECTOR BACKFILL WARNING] {signal_row.get('symbol')}: {exc}")
        except Exception as exc:
            print(f"[SECTOR BACKFILL ERROR] {exc}")

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
