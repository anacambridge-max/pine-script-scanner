create table public.scanner_market_context (
  trade_date date not null,
  symbol text not null,
  instrument_key text not null,
  observed_at timestamptz not null,
  daily_context jsonb not null default '{}'::jsonb,
  sector_context jsonb not null default '{}'::jsonb,
  market_evidence jsonb not null default '{}'::jsonb,
  primary key (trade_date, symbol)
);
alter table public.scanner_market_context enable row level security;
revoke all on public.scanner_market_context from anon, authenticated;
grant select, insert, update on public.scanner_market_context to service_role;
