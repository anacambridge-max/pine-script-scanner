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
- 1m / 3m / 5m timeframe enforcement.
- Asia/Kolkata session handling.
- PDH/PDL, weekly, monthly, 52-week and ATH/ATL levels.
- 09:15-specific RVOL history.
- Opening Candle, Master Candle and Standard Break pathways.
- EMA, candle quality, range expansion/compression.
- Optional five-check confluence gate.
- Fake breakout and WATCH/SETUP/CONFIRMED state machine.
- Prime Score, grade, SL, R targets and risk quantity without SMC dependencies.
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
