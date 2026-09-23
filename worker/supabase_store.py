from __future__ import annotations

import json
import math
import os
from datetime import datetime
from typing import Any

import requests


def _json_safe(value: Any) -> Any:
    """Convert NaN/Infinity and nested non-JSON values into PostgREST-safe JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


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
        response = requests.request(
            method,
            self.base + "/rest/v1/" + path,
            headers=headers,
            timeout=5,
            **kwargs,
        )
        if not response.ok:
            raise RuntimeError(
                f"Supabase {method} failed: {response.status_code} {response.text[:500]}"
            )
        return response

    def write_signal(self, result: dict[str, Any], instrument_key: str, symbol: str, company_name: str | None = None) -> bool:
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
        day = str(ts)[:10]
        signal_id = f"{symbol}|{result.get('timeframe')}|{result.get('direction')}|{day}"

        existing = requests.get(
            self.base + "/rest/v1/scanner_signals",
            headers=self.headers,
            params={"select": "id", "id": f"eq.{signal_id}", "limit": "1"},
            timeout=5,
        )
        if not existing.ok:
            raise RuntimeError(
                f"Supabase signal lookup failed: {existing.status_code} {existing.text[:500]}"
            )
        already_exists = bool(existing.json())

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
            "breakout_level": (
                (result.get("levels") or {}).get(
                    {
                        "PDH": "pdh", "PDL": "pdl",
                        "WEEKLY HIGH": "weekly_high", "WEEKLY LOW": "weekly_low",
                        "MONTHLY HIGH": "monthly_high", "MONTHLY LOW": "monthly_low",
                        "52W HIGH": "year_high", "52W LOW": "year_low",
                        "ATH": "ath", "ATL": "atl",
                    }.get(
                        result.get("buy_break") if result.get("direction") == "BUY"
                        else result.get("sell_break"),
                        "pdh" if result.get("direction") == "BUY" else "pdl",
                    )
                )
            ),
            "score_breakdown": result.get("score_breakdown") or {},
            "reasons": result.get("flags") or {},
            "risks": {
                "risk_per_share": risk.get("risk_per_share"),
                "quantity": risk.get("quantity"),
            },
            "fo_confirmation": "F&O STOCK",
            "is_active": True,
            "signal_time": ts,
            "last_updated": datetime.now().astimezone().isoformat(),
            "metadata": {
                "timeframe": result.get("timeframe"),
                "trigger": result.get("trigger"),
                "company_name": company_name or symbol,
                "full_result": result,
                "sector": result.get("sector"),
                "sector_change_percent": result.get("sector_change_percent"),
                "sector_rank": result.get("sector_rank"),
                "sector_rank_type": result.get("sector_rank_type"),
            },
        }
        row = _json_safe(row)

        if already_exists:
            return False

        self._request(
            "POST",
            "scanner_signals",
            params={"on_conflict": "id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            data=json.dumps(row, default=str, allow_nan=False),
        )
        return True

    def write_next_day_watchlist(self, rows: list[dict[str, Any]], instrument_lookup: dict[str, str]) -> int:
        if not rows:
            return 0
        payload = []
        for row in rows:
            symbol = str(row.get("symbol") or "")
            analysis_date = str(row.get("analysis_date") or "")
            direction = str(row.get("direction") or "")
            row_id = f"{analysis_date}|{symbol}|{direction}"
            item = dict(row)
            item["id"] = row_id
            item["instrument_key"] = instrument_lookup.get(symbol)
            item["target_date"] = str(
                (datetime.fromisoformat(analysis_date).date() + __import__("datetime").timedelta(days=1))
            )
            payload.append(_json_safe(item))
        self._request(
            "POST",
            "next_day_watchlist",
            params={"on_conflict": "id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            data=json.dumps(payload, allow_nan=False),
        )
        return len(payload)

    def get_next_day_watchlist(self, target_date: str | None = None) -> list[dict[str, Any]]:
        if not target_date:
            target_date = datetime.now().date().isoformat()
        response = self._request(
            "GET",
            "next_day_watchlist",
            params={
                "select": "*",
                "target_date": f"eq.{target_date}",
                "order": "direction.asc,score.desc",
                "limit": "20",
            },
        )
        return response.json()

    def delete_previous_days(self) -> int:
        """Delete scanner signals from dates before today."""
        day = datetime.now().date().isoformat()
        response = self._request(
            "DELETE",
            "scanner_signals",
            params={"signal_time": f"lt.{day}T00:00:00"},
            headers={"Prefer": "return=representation"},
        )
        try:
            return len(response.json())
        except Exception:
            return 0

    def heartbeat(
        self,
        status: str,
        universe_count: int,
        captured_count: int,
        error: str | None = None,
    ) -> None:
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

        # PATCH can return 204 even when no row matched, so check existence
        # first. This ensures today's heartbeat is always current.
        existing = requests.get(
            self.base + "/rest/v1/scanner_heartbeat",
            headers=self.headers,
            params={
                "select": "trade_date",
                "trade_date": f"eq.{day}",
                "limit": "1",
            },
            timeout=5,
        )
        if not existing.ok:
            raise RuntimeError(
                f"Supabase heartbeat lookup failed: "
                f"{existing.status_code} {existing.text[:500]}"
            )

        if existing.json():
            response = requests.patch(
                self.base + "/rest/v1/scanner_heartbeat",
                headers={**self.headers, "Prefer": "return=minimal"},
                params={"trade_date": f"eq.{day}"},
                data=json.dumps(row),
                timeout=5,
            )
            if not response.ok:
                raise RuntimeError(
                    f"Supabase heartbeat PATCH failed: "
                    f"{response.status_code} {response.text[:500]}"
                )
        else:
            self._request(
                "POST",
                "scanner_heartbeat",
                headers={"Prefer": "return=minimal"},
                data=json.dumps(row),
            )


    def get_today_confirmed_signals(self) -> list[dict[str, Any]]:
        """Return today's confirmed signals for one-time sector backfill."""
        day = datetime.now().date().isoformat()
        response = self._request(
            "GET",
            "scanner_signals",
            params={
                "select": "id,symbol,signal_type,score,grade,metadata,score_breakdown",
                "signal_time": f"gte.{day}T00:00:00",
                "signal_state": "eq.CONFIRMED",
                "limit": "500",
            },
        )
        return response.json()

    def update_signal_sector(
        self,
        signal_id: str,
        metadata: dict[str, Any],
        score_breakdown: dict[str, Any] | None = None,
        score: int | None = None,
        grade: str | None = None,
    ) -> None:
        row: dict[str, Any] = {"metadata": _json_safe(metadata)}
        if score_breakdown is not None:
            row["score_breakdown"] = _json_safe(score_breakdown)
        if score is not None:
            row["score"] = int(score)
        if grade is not None:
            row["grade"] = grade
        self._request(
            "PATCH",
            "scanner_signals",
            params={"id": f"eq.{signal_id}"},
            headers={"Prefer": "return=minimal"},
            data=json.dumps(row, allow_nan=False),
        )
