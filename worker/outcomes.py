"""Prospective, candle-backed observations of confirmed scanner signals.

Only candles that start after the worker observed a signal can count. A candle
that touches both the target and stop is ambiguous; its intraminute order is
unknowable from OHLC data.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import threading
from typing import Any


HORIZONS = (15, 30, 60)


def observe_outcome(signal: dict[str, Any], candles: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any] | None:
    metadata = signal.get("metadata") or {}
    original = metadata.get("outcome")
    if not isinstance(original, dict) or original.get("version") != 1:
        return None
    outcome = deepcopy(original)
    try:
        confirmed = datetime.fromisoformat(outcome["confirmed_at"])
        entry = float(signal["entry"])
        stop = float(signal["stop_loss"])
        target = float(signal["target1"])
        direction = signal["signal_type"]
        if direction not in {"BUY", "SELL"}:
            return None
        side = 1 if direction == "BUY" else -1
    except (KeyError, TypeError, ValueError):
        return None
    if entry <= 0 or confirmed.tzinfo is None or (side == 1 and not stop < entry < target) or (side == -1 and not target < entry < stop):
        return None
    now = now or datetime.now(confirmed.tzinfo)
    outcome.setdefault("prices", {})
    outcome.setdefault("returns_pct", {})
    outcome.setdefault("first_hit", None)
    for candle in sorted(candles, key=lambda row: row["timestamp"]):
        try:
            start = candle["timestamp"]
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            # Skip any candle containing prices from before confirmation.
            if start.tzinfo is None or start < confirmed:
                continue
            end = start + timedelta(minutes=1)
            if end > now:
                continue
            high, low, close = (float(candle[key]) for key in ("high", "low", "close"))
        except (KeyError, TypeError, ValueError):
            continue
        if high < low or close <= 0:
            continue
        if outcome["first_hit"] is None and start < confirmed + timedelta(minutes=60):
            target_hit = high >= target if side == 1 else low <= target
            stop_hit = low <= stop if side == 1 else high >= stop
            if target_hit or stop_hit:
                outcome["first_hit"] = "AMBIGUOUS" if target_hit and stop_hit else "TARGET" if target_hit else "STOP"
                outcome["first_hit_at"] = end.isoformat()
        for horizon in HORIZONS:
            key = str(horizon)
            if key not in outcome["prices"] and end >= confirmed + timedelta(minutes=horizon):
                # A missing candle around the horizon is not a valid mark.
                if end > confirmed + timedelta(minutes=horizon + 2):
                    continue
                outcome["prices"][key] = round(close, 4)
                outcome["returns_pct"][key] = round(side * (close / entry - 1) * 100, 4)
                outcome["last_observed_at"] = end.isoformat()
    outcome["status"] = "COMPLETE" if all(str(h) in outcome["prices"] for h in HORIZONS) else "PENDING"
    return outcome if outcome != original else None


def new_outcome(confirmed_at: datetime, candle_start_at: str) -> dict[str, Any]:
    return {
        "version": 1, "confirmed_at": confirmed_at.isoformat(),
        "candle_start_at": candle_start_at, "prices": {}, "returns_pct": {},
        "first_hit": None, "status": "PENDING",
    }


class OutcomeMonitor:
    def __init__(self, store: Any, feed: Any):
        self.store = store
        self.feed = feed
        self.pending: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()

    def register(self, row: dict[str, Any]) -> None:
        outcome = (row.get("metadata") or {}).get("outcome") or {}
        if outcome.get("version") != 1 or outcome.get("status") == "COMPLETE":
            return
        if not row.get("instrument_key") or not row.get("id"):
            return
        with self.lock:
            self.pending[row["id"]] = row

    def register_new(self, result: dict[str, Any], instrument_key: str, symbol: str) -> None:
        ts = str(result["timestamp"])
        confirmed = datetime.fromisoformat(result["_confirmed_at"])
        risk = result.get("risk") or {}
        self.register({
            "id": f"{symbol}|{result['timeframe']}|{result['direction']}|{ts[:10]}",
            "instrument_key": instrument_key,
            "signal_type": result["direction"],
            "entry": risk.get("entry"), "stop_loss": risk.get("stop_loss"),
            "target1": risk.get("target1"),
            "metadata": {"outcome": new_outcome(confirmed, ts)},
        })

    def tick(self) -> int:
        with self.lock:
            pending = list(self.pending.items())
        updated = 0
        for signal_id, row in pending:
            # Copy the feed's in-memory minute bars. The websocket may add a
            # newer bar while this background thread computes a snapshot.
            candles = list(self.feed._bars.get(row["instrument_key"], {}).values())
            changed = observe_outcome(row, candles)
            if changed is None:
                continue
            self.store.update_signal_outcome(signal_id, changed)
            row["metadata"]["outcome"] = changed
            updated += 1
            if changed["status"] == "COMPLETE":
                with self.lock:
                    self.pending.pop(signal_id, None)
        return updated
