# Prime Technical Live Scanner

Production-oriented port of the TradingView **Prime Technical — Institutional V2** Pine Script into a broker-neutral Python engine, with an Upstox data layer, always-on worker, and Next.js dashboard.

## Architecture

```
Upstox V3 WebSocket
        |
        v
+-------------------+
| Worker / Aggregator|
+---------+---------+
          |
          v
+-------------------+       +------------------+
| Prime Python      | ----> | Supabase/Postgres|
| Signal Engine     |       +--------+---------+
+-------------------+                |
                                     v
                              Next.js / Vercel
```

Vercel is intentionally not used for a persistent broker WebSocket. The worker is designed to run continuously outside Vercel.

## Current implementation

- Broker-neutral OHLCV signal engine.
- Upstox V3 WebSocket full-feed adapter with live 1-minute OHLC normalization.
- Historical 1-minute and daily seeding before live scanning.
- Persistent day-scoped BUY/SELL CONFIRMED deduplication.
- 1m / 3m / 5m timeframe enforcement.
- Asia/Kolkata session handling.
- PDH/PDL, weekly, monthly, 52-week and ATH/ATL levels.
- 09:15-specific RVOL history.
- Opening Candle, Master Candle and Standard Break pathways.
- EMA, candle quality, range expansion/compression.
- Optional five-check confluence gate.
- Fake breakout and WATCH/SETUP/CONFIRMED state machine.
- Prime Score, grade, SL, R targets and risk quantity without SMC dependencies.
- SMC, BOS/CHoCH, Liquidity Sweep, FVG and Order Block confirmation logic is removed from the scanner.
- Confirmed signals are driven by enabled key levels (PDH/PDL, weekly, monthly, 52-week, ATH/ATL), fresh close-confirmed breaks and extreme volume; no SMC gate is applied.
- Unit-testable pandas implementation.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## Next layers

The repository is intentionally being built in layers:

1. Engine + tests
2. Upstox historical/WebSocket adapter
3. Always-on worker
4. Supabase persistence/realtime
5. Next.js dashboard
6. CI/CD and deployment

Never commit API keys or access tokens. Copy `.env.example` to `.env`.

## Disclaimer

This software is for research and engineering purposes. It is not investment advice. Past signals and backtest results do not guarantee future results.

## Scanner reliability and quality

The live worker now uses QUALITY PRIME: the first PDH/PDL close break must have
at least 2× volume, a candle body of at least 50% of its range, a close in the
outer 40% in the signal direction, 1.3× range expansion, EMA alignment and
same-candle directional follow-through. FAST PRIME remains available in the
engine for explicit comparisons. A score is a setup ranking, not a win probability;
volume points now scale from 20 at 2× to 40 at 4× rather than saturating at 2×.
Validate these stricter rules on historical data before claiming a better hit rate.

The live worker permits one narrow exception to the 1.3× range-expansion rule:
if the completed 09:15 three-minute candle has at least 5× volume, a 60% body,
and a directional close in the outer 30%, a later first PDH/PDL close-break can
confirm without range expansion. The break candle still needs at least 2×
volume, 50% body, 60% directional close, EMA alignment and follow-through.
This captures strong opening participation followed by a genuine level break;
an opening watch alone never becomes a confirmed signal. Pre-market movement
watch now accepts indicative gaps up to 10%, still requiring repeated aligned
snapshots and order pressure. Historic signals are not relabelled retroactively.

The worker rejects incomplete three-minute candles and delayed/replayed bars.
Signals show the candle's start time; confirmation happens after its close.
SIGNAL CLOSE is the recorded signal price, not a current market quote.
The dashboard polls database heartbeats and shows LIVE, STALE, IDLE, OFFLINE or
UNAVAILABLE. LIVE requires recent broker candle data during market hours;
this is feed-level health, not a guarantee that every instrument is current.
Optional panel failures are visible instead of being presented as empty results.

D-1 analysis skips weekends and configured NSE holidays. Missing completed daily
history is re-fetched rather than cached indefinitely. Update NSE_HOLIDAYS annually.
NSE pre-market collection still requires the worker to run during 09:00–09:08 IST.
No eligible news can legitimately produce an empty hot-stock list.

The market-context worker checks same-day stock-watch articles from Upstox and
Moneycontrol, plus Moneycontrol earnings/results coverage. It links to the
publisher article and labels each match by source and category. Article mentions
are context only: they add a small watchlist ranking bonus, never create a
BUY/SELL confirmation or count as verified bullish/bearish news. Articles
published after a watch or signal timestamp are not displayed as support for
that earlier event. If a publisher is unavailable or has no eligible same-day
article, its coverage is omitted while price-based signals continue.

Run `python -m pytest` and `npm run build` to validate changes. Restart the Python
worker and redeploy the Next.js dashboard to activate them. Existing saved signals
are preserved and were generated with the rules active when they were captured.
