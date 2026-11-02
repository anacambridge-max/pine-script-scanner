export type DailyContext = {
  status: string; analysis_date?: string; nr4?: boolean; nr7?: boolean; narrow_pd?: boolean;
  compression?: boolean; pdh?: number; pdl?: number; range_pct?: number; range_vs_prior20?: number | null;
  trend?: string; labels?: string[]; body_ratio?: number; close_location?: number; previous_close?: number;
};

export type MovementEvidence = {confirmed_at: string; observed_at: string; oi?: {label?: string}; news?: {impact: string; published_at: string; title: string}[]};
export type NseFiling = {title: string; url: string; published_at: string; source: string; period: "SAME DAY" | "PREVIOUS SESSION"; impact: string; context?: string; category?: string};
export function latestFiling(filings: NseFiling[] | undefined, cutoff: string | null | undefined): NseFiling | undefined {
  const limit = Date.parse(cutoff ?? "");
  if (!Number.isFinite(limit)) return undefined;
  return filings?.filter(item => Number.isFinite(Date.parse(item.published_at)) && Date.parse(item.published_at) <= limit)
    .sort((a, b) => Number(b.category === "RESULTS") - Number(a.category === "RESULTS") || Date.parse(b.published_at) - Date.parse(a.published_at))[0];
}
export type PatternFilter = "ALL" | "MOVERS" | "STRONG" | "GAINERS" | "LOSERS" | "NR7" | "NR4" | "NARROW" | "SUPPORTED";
export function confirmedPatternHint(signal: {signal_state?: string | null; signal_type: string; entry?: number | null; rvol?: number | null; metadata?: {daily_context?: DailyContext; movement_evidence?: MovementEvidence; full_result?: {body_ratio?: number; close_location?: number}}}, daily?: DailyContext) {
  const context = signal.metadata?.daily_context?.status === "READY" ? signal.metadata.daily_context : daily;
  const labels = context?.status === "READY" ? [context.nr7 && "NR7", context.nr4 && "NR4", context.narrow_pd && "NARROW PD RANGE"].filter(Boolean) as string[] : [];
  const candle = signal.metadata?.full_result;
  const body = candle?.body_ratio;
  const location = candle?.close_location;
  const buy = signal.signal_type === "BUY";
  const sell = signal.signal_type === "SELL";
  const beyondRange = signal.entry != null && (buy ? context?.pdh != null && signal.entry > context.pdh : sell && context?.pdl != null && signal.entry < context.pdl);
  const evidence = signal.metadata?.movement_evidence;
  const observed = Date.parse(evidence?.observed_at ?? "");
  const confirmed = Date.parse(evidence?.confirmed_at ?? "");
  const timely = Number.isFinite(observed) && Number.isFinite(confirmed) && confirmed >= observed && confirmed-observed <= 180000;
  const oi = timely && (buy ? ["LONG BUILDUP", "SHORT COVERING"] : ["SHORT BUILDUP", "LONG UNWINDING"]).includes(evidence?.oi?.label ?? "") ? evidence?.oi?.label : null;
  const news = timely ? evidence?.news?.filter(item => Date.parse(item.published_at) <= confirmed && (buy ? /BULLISH|POSITIVE/.test(item.impact) : /BEARISH|NEGATIVE/.test(item.impact))) ?? [] : [];
  const alignedTrend = buy ? context?.trend === "UPTREND" : sell && context?.trend === "DOWNTREND";
  const qualified = signal.signal_state === "CONFIRMED" && (context?.compression || alignedTrend && (oi || news.length > 0)) && beyondRange && (signal.rvol ?? 0) >= 2 && body != null && body >= .5 && body <= 1 && location != null && location >= .65 && location <= 1;
  const supporting = [oi, news.length > 0 ? "Fresh aligned news at confirmation" : null].filter(Boolean) as string[];
  return {labels, label: qualified ? buy ? "Potential Top Gainer" : "Potential Top Loser" : null,
    supporting, reason: qualified ? `Prior-session ${labels.join(" / ") || context?.trend} · confirmed PD${buy ? "H" : "L"} close-break · strong 3M candle · RVOL ${signal.rvol}×${supporting.length ? " · " + supporting.join(" · ") : ""}. Conditional watch, not a probability estimate.` : null};
}
export function matchesPatternFilter(signal: Parameters<typeof confirmedPatternHint>[0], daily: DailyContext | undefined, filter: PatternFilter) {
  if (filter === "ALL") return true;
  if (signal.signal_state !== "CONFIRMED") return false;
  const hint = confirmedPatternHint(signal, daily);
  switch (filter) {
    case "MOVERS": return hint.label != null;
    case "GAINERS": return hint.label === "Potential Top Gainer";
    case "LOSERS": return hint.label === "Potential Top Loser";
    case "NR7": return hint.labels.includes("NR7");
    case "NR4": return hint.labels.includes("NR4");
    case "NARROW": return hint.labels.includes("NARROW PD RANGE");
    case "SUPPORTED": return hint.label != null && hint.supporting.length > 0;
    case "STRONG": return hint.label != null && (signal.rvol ?? 0) >= 3 &&
      (signal.metadata?.full_result?.body_ratio ?? 0) >= .65 &&
      (signal.metadata?.full_result?.close_location ?? 0) >= .8;
  }
}
export type SectorContext = {
  sector?: string | null; sector_change?: number | null; sector_gainer_rank?: number | null;
  sector_loser_rank?: number | null; sector_observed_at?: string | null; sector_fresh?: boolean;
};
export type MarketContextRow = {
  symbol: string; observed_at: string; daily_context: DailyContext; sector_context: SectorContext;
  market_evidence: {
    candle: {status: string; change_pct?: number; gap_pct?: number; body_ratio?: number; close_location?: number; labels?: string[]};
    opening?: {status: string; timestamp?: string; previous_close?: number; open?: number; high?: number; low?: number; close?: number; volume?: number; gap_pct?: number; move_pct?: number; body_ratio?: number; close_location?: number; volume_multiple?: number | null; baseline_bars?: number; baseline_session?: string | null; volume_reference?: string};
    oi: {label: string; change_pct?: number | null; futures_price_change_pct?: number | null; contract?: string | null; quote_time?: string | null};
    news: {title: string; url: string; published_at: string; context?: string; impact: string}[];
    filings?: NseFiling[];
    quote_time?: string; volume_vs_daily20?: number | null; news_status?: string;
  };
};

export function sectorSupport(context: SectorContext | undefined, direction: string, now = new Date()): {bonus: number; label: string} {
  if (!context || !context.sector_observed_at || !context.sector_fresh) return {bonus: 0, label: "Sector data unavailable"};
  const observed = new Date(context.sector_observed_at);
  const date = (value: Date) => new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Kolkata"}).format(value);
  if (!Number.isFinite(observed.getTime()) || date(observed) !== date(now)) return {bonus: 0, label: "Sector data stale"};
  const minutes = Number(new Intl.DateTimeFormat("en-GB", {timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).format(now).split(":")[0]) * 60 + Number(new Intl.DateTimeFormat("en-GB", {timeZone: "Asia/Kolkata", minute: "2-digit"}).format(now));
  if (minutes >= 9*60+15 && minutes < 15*60+30 && now.getTime()-observed.getTime() > 180000) return {bonus: 0, label: "Sector data stale"};
  const change = context.sector_change;
  if (change == null || !Number.isFinite(change)) return {bonus: 0, label: "Sector data unavailable"};
  const buy = direction.includes("BUY") || direction === "UP WATCH";
  const sell = direction.includes("SELL") || direction === "DOWN WATCH";
  if (buy && change > 0 && context.sector_gainer_rank != null && context.sector_gainer_rank >= 1 && context.sector_gainer_rank <= 3) return {bonus: 10, label: `Sector Top Gainer #${context.sector_gainer_rank}`};
  if (sell && change < 0 && context.sector_loser_rank != null && context.sector_loser_rank >= 1 && context.sector_loser_rank <= 3) return {bonus: 10, label: `Sector Top Loser #${context.sector_loser_rank}`};
  return {bonus: 0, label: context.sector ? `${context.sector} ${change.toFixed(2)}%` : "Sector membership unavailable"};
}

export function isOpeningSignal(metadata: {opening_candle?: {is_opening?: boolean}; full_result?: {timestamp?: string}}, signalTime?: string | null): boolean {
  if (metadata.opening_candle?.is_opening != null) return metadata.opening_candle.is_opening;
  // Legacy rows stored candle start, while newer rows store observation time.
  const value = metadata.full_result?.timestamp || signalTime;
  if (!value) return false;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return false;
  return new Intl.DateTimeFormat("en-GB", {timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).format(date) === "09:15";
}
