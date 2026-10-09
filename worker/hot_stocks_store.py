"""Persistence helpers for supplemental morning watchlists."""
from __future__ import annotations
import json
from typing import Any
from worker.supabase_store import _json_safe

def write_technical_watch(store: Any, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    payload=[]
    for row in rows:
        item=dict(row)
        item["id"]=f"{item.get('trade_date','')}|{item.get('symbol','')}"
        item["setup"]="TECHNICAL ONLY WATCH"
        payload.append(_json_safe(item))
    store._request("POST","morning_technical_watch",params={"on_conflict":"id"},
        headers={"Prefer":"resolution=merge-duplicates,return=minimal"},
        data=json.dumps(payload,default=str,allow_nan=False))
    return len(payload)

def clear_technical_watch(store: Any, trade_date: str) -> None:
    """Remove the previous snapshot so an empty current scan cannot show stale candidates."""
    store._request("DELETE", "morning_technical_watch", params={"trade_date": f"eq.{trade_date}"})
