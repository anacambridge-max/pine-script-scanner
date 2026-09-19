from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import requests


class SupabaseStore:
    def __init__(self) -> None:
        self.base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not self.base or not self.key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")

        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}))
        response = requests.request(method, self.base + "/rest/v1/" + path, headers=headers, timeout=20, **kwargs)
        if not response.ok:
            raise RuntimeError(f"Supabase {method} failed: {response.status_code} {response.text[:500]}")
        return response

    def write_signal(self, result: dict[str, Any], instrument_key: str, symbol: str) -> None:
        risk = result.get("risk") or {}
        entry = risk.get("entry")
        stop = risk.get("stop_loss")
        target1 = risk.get("target1")
        rr = None
        if entry is not None and stop is not None and target1 is not None:
            risk_per_share = abs(float(entry) - float(stop))
            if risk_per_share > 0:
                rr = abs(float(target1) - float(entry)) / risk_per_share

        ts = result.get("timestamp")
        signal_id = f"{symbol}|{result.get('timeframe')}|{result.get('direction')}|{ts}"
        row = {
            "id": signal_id,
            "symbol": symbol,
            "instrument_key": instrument_key,
            "signal_type": result.get("direction"),
            "signal_state": result.get("state"),
            "score": int(result.get("prime_score") or 0),
            "grade": result.get("grade"),
            "ltp": entry,
            "entry": entry,
            "stop_loss": stop,
            "target1": target1,
            "target2": risk.get("target2"),
            "risk_reward": rr,
            "setup": result.get("trigger"),
            "ema20_status": result.get("ema_status"),
            "rvol": result.get("volume_multiple"),
            "volume_grade": result.get("volume_tier"),
            "breakout_level": (result.get("levels") or {}).get("pdh" if result.get("direction") == "BUY" else "pdl"),
            "score_breakdown": {},
            "reasons": result.get("flags") or {},
            "risks": {"risk_per_share": risk.get("risk_per_share"), "quantity": risk.get("quantity")},
            "fo_confirmation": "F&O STOCK",
            "is_active": True,
            "signal_time": ts,
            "last_updated": datetime.now().isoformat(),
            "metadata": {
                "timeframe": result.get("timeframe"),
                "trigger": result.get("trigger"),
                "full_result": result,
            },
        }
        self._request(
            "POST",
            "scanner_signals",
            params={"on_conflict": "id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            data=json.dumps(row, default=str),
        )

    def heartbeat(self, status: str, universe_count: int, captured_count: int, error: str | None = None) -> None:
        now = datetime.now().astimezone().isoformat()
        day = datetime.now().date().isoformat()
        row = {
            "trade_date": day,
            "last_run_at": now,
            "universe_count": universe_count,
            "captured_count": captured_count,
            "status": status,
            "error": error,
            "updated_at": now,
        }
        # Patch today's row first; insert it if it doesn't exist.
        response = requests.patch(
            self.base + "/rest/v1/scanner_heartbeat",
            headers={**self.headers, "Prefer": "return=minimal"},
            params={"trade_date": f"eq.{day}"},
            data=json.dumps(row),
            timeout=20,
        )
        if response.ok and response.headers.get("content-range", "").endswith("/0") is False:
            return
        self._request("POST", "scanner_heartbeat", data=json.dumps(row))
