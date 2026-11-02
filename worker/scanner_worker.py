from __future__ import annotations

import os
import json
import signal
import threading
import time
import traceback
from typing import Any
from datetime import timedelta

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
from worker.outcomes import OutcomeMonitor
from worker.market_context import MarketContext


class ScannerWorker:
    def __init__(self):
        token = os.getenv("UPSTOX_ACCESS_TOKEN")
        if not token:
            raise RuntimeError("UPSTOX_ACCESS_TOKEN is required")

        self.access_token = token
        self.engine = PrimeEngine(PrimeConfig(
            signal_mode="QUALITY PRIME", use_ema_filter=True,
            require_follow_through=True, opening_impulse_range_exception=True,
        ))
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
        self.outcomes = OutcomeMonitor(self.supabase, self.feed)
        self.market_context = MarketContext(self)
        self.running = True
        self.captured_count = 0
        self.last_heartbeat = 0.0
        self._heartbeat_thread: threading.Thread | None = None
        self._premarket_thread: threading.Thread | None = None

    def _new_feed(self) -> UpstoxV3Feed:
        feed = UpstoxV3Feed(self.access_token, list(self.instrument_map))
        feed.on_bar(self._on_bar)
        return feed

    @staticmethod
    def _aggregate_ohlcv(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
        x = df.copy().drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
        # Only regular-session candles contribute to levels and confirmation.
        x = x.between_time("09:15", "15:29")
        grouped = x.resample(f"{minutes}min", origin="start_day", offset=pd.Timedelta(900, unit="s"))
        bars = grouped.agg(
            open=("open", "first"), high=("high", "max"),
            low=("low", "min"), close=("close", "last"), volume=("volume", "sum"),
            source_count=("close", "count"),
        )
        # Retain known historical extrema even when a minute is missing.
        # Dropping a partial historical bar can lower PDH or raise PDL and
        # manufacture a breakout. Live session completeness is checked below.
        return bars.loc[bars.source_count.gt(0)].dropna().reset_index()

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
        if status == "LIVE":
            clock = pd.Timestamp.now(tz="Asia/Kolkata")
            from worker.hot_stocks_config import NSE_HOLIDAYS
            trading = clock.weekday() < 5 and clock.date().isoformat() not in NSE_HOLIDAYS
            if not trading or not ("09:15" <= clock.strftime("%H:%M") < "15:30"):
                status = "IDLE"
            elif now - self.feed.last_data_at > 90:
                status = "STALE"
        if now - self.last_heartbeat < 25 and status in {"LIVE", "IDLE", "STALE"}:
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
        # Heartbeats stay independent from NSE HTTP latency.
        while self.running:
            self._heartbeat("LIVE")
            for _ in range(30):
                if not self.running:
                    return
                time.sleep(1)

    def _premarket_study_loop(self) -> None:
        # Poll frequently enough to capture each minute from 09:00 through
        # 09:08 IST. _run_nse_premarket_study deduplicates by minute, so these
        # checks do not create duplicate snapshots. Keep this separate from
        # heartbeats and the confirmed BUY/SELL feed.
        while self.running:
            try:
                self._run_nse_premarket_study()
            except Exception as exc:
                print(f"[NSE PRE-MARKET WARNING] {exc}")
            for _ in range(5):
                if not self.running:
                    return
                time.sleep(1)

    def _morning_hot_loop(self) -> None:
        # Retry during pre-open even when the worker starts before 09:00.
        # A one-shot startup call can miss the valid news window entirely.
        while self.running:
            try:
                self.market_context.refresh()
            except Exception as exc:
                print(f"[MARKET CONTEXT WARNING] {type(exc).__name__}: {exc}")
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

        now = pd.Timestamp.now(tz="Asia/Kolkata")
        age = (now - completed_1m_ts).total_seconds()
        if completed_1m_ts.date() != now.date() or not 60 <= age <= 180:
            return

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
            if frame.empty or frame["timestamp"].iloc[-1] + pd.Timedelta((timeframe - 1) * 60, unit="s") != completed_1m_ts:
                continue
            if timeframe != 1:
                session = frame.loc[frame["timestamp"].dt.date == completed_1m_ts.date()]
                session_start = completed_1m_ts.replace(hour=9, minute=15, second=0, microsecond=0)
                expected = pd.date_range(session_start, frame["timestamp"].iloc[-1], freq=f"{timeframe}min")
                # Every candle since the open must be complete: a missing
                # earlier candle could hide the day's actual first break.
                if not session["source_count"].eq(timeframe).all() or not pd.DatetimeIndex(session["timestamp"]).equals(expected):
                    continue
            if len(frame) < 30:
                continue

            try:
                # Evaluate the trading signal FIRST. Sector data is optional
                # scoring context and must never block or delay the live scanner.
                context_service = getattr(self, "market_context", None)
                daily = context_service.daily.get(instrument_key) if context_service else None
                result: dict[str, Any] = self.engine.evaluate(
                    frame, timeframe, context={"daily_context": daily} if daily else None
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
                            frame, timeframe, context={**sector_context, "daily_context": daily}
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
                    context_service = getattr(self, "market_context", None)
                    daily = context_service.daily.get(instrument_key) if context_service else None
                    result["daily_context"] = daily or {"status": "PENDING"}
                    snapshot = getattr(context_service, "latest_rows", {}).get(instrument_key)
                    if snapshot:
                        observed = pd.Timestamp(snapshot["observed_at"])
                        if 0 <= (now - observed).total_seconds() <= 180:
                            result["movement_evidence"] = {
                                "confirmed_at": now.isoformat(),
                                "observed_at": snapshot["observed_at"],
                                "oi": snapshot["market_evidence"]["oi"],
                                "news": snapshot["market_evidence"]["news"],
                            }
                    candle_ts = pd.Timestamp(result["timestamp"])
                    result["opening_candle"] = {
                        "is_opening": candle_ts.hour == 9 and candle_ts.minute == 15 and timeframe == 3,
                        "body_ratio": result.get("body_ratio"), "close_location": result.get("close_location"),
                        "range_expansion": result.get("range_expansion"),
                        "volume_multiple": result.get("volume_multiple"),
                    }
                    company_name = self.company_map.get(instrument_key, symbol)
                    inserted = self.supabase.write_signal(
                        result, instrument_key, symbol, company_name
                    )
                    if inserted:
                        self.outcomes.register_new(result, instrument_key, symbol)
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
        from worker.hot_stocks_config import NSE_HOLIDAYS
        target = analysis_date.date() + timedelta(days=1)
        while target.weekday() >= 5 or target.isoformat() in NSE_HOLIDAYS:
            target += timedelta(days=1)
        return target.isoformat()

    @staticmethod
    def _previous_business_day(analysis_date: pd.Timestamp) -> pd.Timestamp:
        """Return the latest calendar trading day before the supplied date."""
        from worker.hot_stocks_config import NSE_HOLIDAYS
        target = analysis_date.date() - timedelta(days=1)
        while target.weekday() >= 5 or target.isoformat() in NSE_HOLIDAYS:
            target -= timedelta(days=1)
        return pd.Timestamp(target)


    @staticmethod
    def _completed_session(now: pd.Timestamp) -> pd.Timestamp:
        from worker.hot_stocks_config import NSE_HOLIDAYS
        day = now.date()
        if (now.hour, now.minute) < (15, 35):
            day -= timedelta(days=1)
        while day.weekday() >= 5 or day.isoformat() in NSE_HOLIDAYS:
            day -= timedelta(days=1)
        return pd.Timestamp(day, tz="Asia/Kolkata")

    def _run_nse_premarket_study(self) -> None:
        now = pd.Timestamp.now(tz="Asia/Kolkata")
        # Keep the collector strictly inside the requested NSE 09:00–09:08
        # IST order-collection window and skip exchange holidays before any
        # network request. The collector independently enforces the same gate.
        from worker.hot_stocks_config import NSE_HOLIDAYS
        if (
            now.weekday() >= 5
            or now.date().isoformat() in NSE_HOLIDAYS
            or not (now.hour == 9 and 0 <= now.minute <= 8)
        ):
            return
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        if minute_key == self._premarket_snapshot_minute:
            return
        from worker.nse_premarket import NSEPreMarketStudy
        snapshot = NSEPreMarketStudy().collect(
            now.to_pydatetime(),
            allowed_symbols=set(self.instrument_map.values()),
        )
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
            news_items = fetch_moneycontrol_news(max_items=80, timestamped_only=True)
            print(f"[MORNING] Moneycontrol headlines loaded: {len(news_items)}")

            # Use compact daily candles for the pre-open technical scan. The
            # heavy 1-minute seed is reserved for the live 3M engine.
            histories = self.market_context.histories if self.market_context.day == trade_date else self.feed.get_daily_histories(lookback_days=60)
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
            # Reaching this point means the persistence steps completed. A
            # non-empty news fetch with zero qualifying candidates is a valid
            # empty scan; a completely empty feed response stays retryable.
            if count > 0 or technical_count > 0 or len(news_items) > 0:
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
                self._daily_history_cache.pop(cache_key, None)
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
                self._daily_history_cache.pop(cache_key, None)
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

                analysis_date = self._completed_session(now)
                if after_close and analysis_date.date() == now.date() and not refreshed_today:
                    print("[D-1] Market close reached; checking today's completed session.")
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

    def _wait_for_feed_close(self) -> bool:
        """A wait timeout is a healthy connection, not a reconnect request."""
        while self.running:
            if self.feed.wait_until_closed(timeout=1):
                return True
        return False

    def run(self) -> None:
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        self._heartbeat("STARTING")
        # Preserve prior sessions for prospective outcome measurement.
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="scanner-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()
        self._premarket_thread = threading.Thread(
            target=self._premarket_study_loop,
            name="nse-premarket-study",
            daemon=True,
        )
        self._premarket_thread.start()

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
        self.feed.seed_current_session()
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
                    self.outcomes.register(signal_row)
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

        threading.Thread(target=self._outcome_loop, name="signal-outcomes", daemon=True).start()

        reconnect_delay = 20

        while self.running:
            try:
                print("Connecting to Upstox V3 WebSocket...")
                self.feed.connect()
                # connect() starts the SDK's websocket thread and returns
                # immediately. Wait for its actual close event before creating
                # another streamer; rebuilding immediately causes overlapping
                # handshakes and Upstox 403 responses.
                self._wait_for_feed_close()

                if self.running:
                    print(
                        f"Upstox connection closed; waiting {reconnect_delay}s "
                        "before rebuilding connection..."
                    )
                    self._heartbeat("RECONNECTING")
                    time.sleep(reconnect_delay)
                    if not self.running:
                        break
                    # Keep seeded/live candles and emission cursors across
                    # reconnections; replace only the disconnected transport.
                    self.feed.rebuild_streamer()
                    reconnect_delay = min(reconnect_delay + 10, 60)

            except Exception as exc:
                self._heartbeat("RECONNECTING", str(exc))
                print(
                    f"[FEED ERROR] {exc}; waiting {reconnect_delay}s "
                    "before rebuilding..."
                )
                time.sleep(reconnect_delay)
                if self.running:
                    self.feed.rebuild_streamer()
                reconnect_delay = min(reconnect_delay + 10, 60)

    def _outcome_loop(self) -> None:
        while self.running:
            try:
                updated = self.outcomes.tick()
                if updated:
                    print(f"[OUTCOME] Updated {updated} signal observations")
            except Exception as exc:
                print(f"[OUTCOME WARNING] {exc}")
            for _ in range(30):
                if not self.running:
                    return
                time.sleep(1)


if __name__ == "__main__":
    ScannerWorker().run()
