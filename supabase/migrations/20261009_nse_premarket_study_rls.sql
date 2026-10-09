-- Defense in depth: the worker/API uses the service role; browser roles get no direct table access.
alter table public.nse_premarket_study enable row level security;
