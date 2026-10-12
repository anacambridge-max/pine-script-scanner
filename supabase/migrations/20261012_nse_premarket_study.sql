-- NSE pre-open + OI spurts snapshots collected from 09:00 to 09:08 IST.
-- Separate from the confirmed BUY/SELL signals table.
create table if not exists public.nse_premarket_study (
  id text primary key,
  snapshot_time timestamptz not null,
  trade_date date not null,
  symbol text not null,
  previous_close numeric,
  indicative_price numeric,
  indicative_gap_pct numeric,
  indicative_tradable_qty numeric,
  buy_qty numeric,
  sell_qty numeric,
  imbalance_qty numeric,
  oi_change_pct numeric,
  oi_volume numeric,
  preopen_score integer not null default 0,
  preopen_bias text not null default 'NEUTRAL / MIXED',
  reasons jsonb not null default '[]'::jsonb,
  source_preopen text,
  source_oi text,
  created_at timestamptz not null default now()
);
create index if not exists nse_premarket_study_trade_date_idx
  on public.nse_premarket_study (trade_date, snapshot_time desc);
create index if not exists nse_premarket_study_symbol_idx
  on public.nse_premarket_study (symbol, snapshot_time desc);

-- RLS is enabled; server-side service-role API access remains available.
alter table public.nse_premarket_study enable row level security;
