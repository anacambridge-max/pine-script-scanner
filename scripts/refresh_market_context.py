"""Refresh context without starting a second scanner or sending notifications."""
from pathlib import Path
import json
import os
import shlex
from types import SimpleNamespace

from worker.instruments import load_fno_stock_instruments
from worker.market_context import MarketContext
from worker.sector_ranker import SectorRanker
from worker.supabase_store import SupabaseStore
from worker.upstox_feed import UpstoxV3Feed


def main():
    for line in Path(".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        parsed = shlex.split(value, comments=True)
        if parsed:
            os.environ.setdefault(key.strip(), parsed[0])
    instruments = load_fno_stock_instruments()
    worker = SimpleNamespace(instruments=instruments, access_token=os.environ["UPSTOX_ACCESS_TOKEN"],
        feed=UpstoxV3Feed(os.environ["UPSTOX_ACCESS_TOKEN"], [item["instrument_key"] for item in instruments]),
        sector_ranker=SectorRanker(), supabase=SupabaseStore())
    collector = MarketContext(worker)
    rows = collector.refresh(force=True)
    output = Path("data/market-context-latest.json")
    output.write_text(json.dumps(rows, indent=2, default=str))
    # Daily context uses only completed prior sessions; backfill never changes
    # confirmation or prospective outcomes, nor recreates historic signals.
    by_symbol = {row["symbol"]: row for row in rows}
    for signal in worker.supabase.get_today_confirmed_signals():
        context = by_symbol.get(signal["symbol"])
        if not context:
            continue
        metadata = dict(signal.get("metadata") or {})
        metadata["daily_context"] = context["daily_context"]
        metadata["daily_context_backfilled"] = True
        worker.supabase.update_signal_sector(signal["id"], metadata)
    print(f"Saved {len(rows)} market-context rows and enriched today's existing signals.")
    for symbol in ("IRFC", "DELHIVERY", "NUVAMA", "WELCORP", "ZEEL"):
        row = by_symbol.get(symbol)
        if row:
            print(json.dumps(row, default=str))


if __name__ == "__main__":
    main()
