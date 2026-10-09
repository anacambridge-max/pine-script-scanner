-- NSE 09:00–09:08 pre-market study snapshots. Apply this migration in Supabase SQL Editor.
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
create index if not exists nse_premarket_study_snapshot_idx
  on public.nse_premarket_study (snapshot_time desc, preopen_score desc);
create index if not exists nse_premarket_study_symbol_idx
  on public.nse_premarket_study (trade_date, symbol);
