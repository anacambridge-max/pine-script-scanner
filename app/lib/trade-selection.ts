import { confirmedPatternHint, DailyContext } from './market-context';

type Candidate = Parameters<typeof confirmedPatternHint>[0] & {
  symbol: string; stop_loss?: number | null; signal_time?: string | null;
  metadata?: Parameters<typeof confirmedPatternHint>[0]["metadata"] & {sector_rank_type?: string};
};

// Ordered decision rules, not a weighted score or estimated win probability.
export function selectionRules(signal: Candidate, daily?: DailyContext) {
  const body = signal.metadata?.full_result?.body_ratio;
  const close = signal.metadata?.full_result?.close_location;
  const validCandle = body != null && close != null && body >= 0 && body <= 1 && close >= 0 && close <= 1;
  const candleTier = validCandle ? body >= .65 && close >= .8 ? 2 : body >= .5 && close >= .65 ? 1 : 0 : -1;
  const entry = signal.entry;
  const stop = signal.stop_loss;
  const buy = signal.signal_type === 'BUY';
  const validRisk = entry != null && stop != null && Number.isFinite(entry) && Number.isFinite(stop) && entry > 0 && stop > 0 && (buy ? stop < entry : stop > entry);
  const riskPct = validRisk ? Math.abs(entry! - stop!) / entry! * 100 : null;
  const riskTier = riskPct == null ? -1 : riskPct <= 1 ? 2 : riskPct <= 2 ? 1 : 0;
  const hint = confirmedPatternHint(signal, daily);
  const context = signal.metadata?.daily_context?.status === 'READY' ? signal.metadata.daily_context : daily;
  const alignedTrend = buy ? context?.trend === 'UPTREND' : context?.trend === 'DOWNTREND';
  const rvol = Number.isFinite(signal.rvol) ? signal.rvol! : 0;
  const volumeTier = rvol >= 6.5 ? 3 : rvol >= 4 ? 2 : rvol >= 2 ? 1 : 0;
  const sectorAligned = signal.metadata?.sector_rank_type === (buy ? "TOP 3 GAINER" : "TOP 3 LOSER");
  const tier = candleTier === 2 && riskTier >= 1 && volumeTier >= 1 ? 'CLEAN SETUP' : 'REVIEW SETUP';
  return {
    priority: [candleTier, riskTier, Number(hint.supporting.length > 0), Number(sectorAligned), Number(context?.compression), Number(alignedTrend), volumeTier, validCandle ? close! : -1, validCandle ? body! : -1],
    tier,
    reasons: [validCandle ? `Body ${Math.round(body! * 100)}% · close ${Math.round(close! * 100)}%` : 'Candle evidence unavailable', riskPct == null ? 'Invalid/missing SL' : `SL distance ${riskPct.toFixed(2)}%`, `RVOL ${rvol.toFixed(2)}×`, ...hint.labels, ...hint.supporting, ...(sectorAligned ? [buy ? "Sector top gainer at signal" : "Sector top loser at signal"] : []), ...(alignedTrend ? ['Daily trend aligned'] : [])],
  };
}

export function compareSelections(a: ReturnType<typeof selectionRules> & {signal: Candidate}, b: ReturnType<typeof selectionRules> & {signal: Candidate}) {
  for (let i = 0; i < a.priority.length; i++) {
    const difference = b.priority[i] - a.priority[i];
    if (difference) return difference;
  }
  return (a.signal.signal_time ?? '').localeCompare(b.signal.signal_time ?? '') || a.signal.symbol.localeCompare(b.signal.symbol);
}
