-- Apply in Supabase SQL Editor before enabling the Technical-only Watch API.
-- Separate table avoids changing the existing morning_hot_stocks unique key.
create table if not exists public.morning_technical_watch (
  id text primary key,
  trade_date date not null,
  created_at timestamptz not null default now(),
  symbol text not null,
  instrument_key text,
  company_name text,
  score integer not null default 0,
  technical_score integer not null default 0,
  news_score integer not null default 0,
  close numeric,
  change_percent numeric,
  volume_multiple numeric,
  body_ratio numeric,
  range_expansion numeric,
  compression_score numeric,
  breakout_proximity numeric,
  news_impact text,
  news_summary text,
  news_titles jsonb not null default '[]'::jsonb,
  reasons jsonb not null default '[]'::jsonb,
  setup text not null default 'TECHNICAL ONLY WATCH'
);
create index if not exists morning_technical_watch_date_score_idx
  on public.morning_technical_watch (trade_date desc, score desc);
