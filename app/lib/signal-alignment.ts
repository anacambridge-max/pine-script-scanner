import type { MarketContextRow } from './market-context';

type Signal = {
  symbol: string; signal_type: string; signal_state: string | null;
  signal_time: string | null;
  metadata?: {
    full_result?: {timestamp?: string};
    sector_rank_type?: string;
    movement_evidence?: {
      confirmed_at: string; observed_at: string;
      oi?: {label?: string};
      news?: {impact: string; published_at: string; title: string}[];
    };
  };
};
type PreMarket = {symbol: string; movement_direction: string; snapshot_time: string};

const istDay = (value: number) => new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Kolkata'}).format(new Date(value));
const validTime = (value?: string | null) => {
  const parsed = Date.parse(value ?? '');
  return Number.isFinite(parsed) ? parsed : null;
};

// Four independent clues. None is a gate for the underlying 3M confirmation.
export function signalAlignment(signal: Signal, premarket: PreMarket[], context?: MarketContextRow) {
  const labels: string[] = [];
  const unavailable: string[] = [];
  const buy = signal.signal_type === 'BUY';
  const confirmedAt = validTime(signal.metadata?.movement_evidence?.confirmed_at) ??
    (validTime(signal.metadata?.full_result?.timestamp) != null
      ? validTime(signal.metadata?.full_result?.timestamp)! + 180000
      : validTime(signal.signal_time));
  if (signal.signal_state !== 'CONFIRMED' || (signal.signal_type !== 'BUY' && signal.signal_type !== 'SELL') || confirmedAt == null) {
    return {count: 0, labels, unavailable: ['Confirmation time unavailable']};
  }
  const direction = buy ? 'UP WATCH' : 'DOWN WATCH';
  const symbol = signal.symbol.trim().toUpperCase();
  const preRows = premarket.filter(row => row.symbol.trim().toUpperCase() === symbol &&
    validTime(row.snapshot_time) != null && validTime(row.snapshot_time)! <= confirmedAt &&
    istDay(validTime(row.snapshot_time)!) === istDay(confirmedAt));
  if (preRows.some(row => row.movement_direction === direction)) labels.push('Pre-market aligned');
  else if (!preRows.length) unavailable.push('Pre-market');

  const opening = context?.market_evidence?.opening;
  const openingAt = validTime(opening?.timestamp);
  if (opening?.status === 'READY' && openingAt != null && openingAt + 60000 <= confirmedAt &&
      istDay(openingAt) === istDay(confirmedAt)) {
    const close = opening.close;
    const open = opening.open;
    const volume = opening.volume_multiple;
    const move = opening.move_pct;
    const body = opening.body_ratio;
    const location = opening.close_location;
    if (open != null && close != null && volume != null && move != null && body != null && location != null) {
      const directionalClose = buy ? location : 1 - location;
      const gap = opening.gap_pct ?? 0;
      const gapDriven = Math.abs(gap) >= 2 && Math.sign(gap) === (buy ? 1 : -1) && volume >= 10 && body >= .3 && directionalClose >= .65;
      if ((buy ? close > open && move > 0 : close < open && move < 0) && volume >= 3 && Math.abs(move) >= .5 &&
          (gapDriven || body >= .35 && directionalClose >= .7)) labels.push(`Opening aligned · ${volume.toFixed(1)}× volume`);
    }
  } else unavailable.push('Opening candle');

  const sector = signal.metadata?.sector_rank_type;
  if (sector === (buy ? 'TOP 3 GAINER' : 'TOP 3 LOSER')) labels.push(buy ? 'Sector top 3 gainer' : 'Sector top 3 loser');
  else if (!sector) unavailable.push('Sector at signal');

  const evidence = signal.metadata?.movement_evidence;
  const observedAt = validTime(evidence?.observed_at);
  if (observedAt != null && observedAt <= confirmedAt && confirmedAt - observedAt <= 180000) {
    const oi = evidence?.oi?.label;
    const oiAligned = buy ? ['LONG BUILDUP', 'SHORT COVERING'].includes(oi ?? '') : ['SHORT BUILDUP', 'LONG UNWINDING'].includes(oi ?? '');
    const newsAligned = evidence?.news?.some(item => {
      const published = validTime(item.published_at);
      return published != null && published <= confirmedAt && istDay(published) === istDay(confirmedAt) &&
        (buy ? /BULLISH|POSITIVE/i.test(item.impact) : /BEARISH|NEGATIVE/i.test(item.impact));
    });
    if (oiAligned || newsAligned) labels.push([oiAligned && 'OI', newsAligned && 'News'].filter(Boolean).join(' + ') + ' aligned');
    else if (!oi && !evidence?.news?.length) unavailable.push('News/OI');
  } else unavailable.push('News/OI');
  return {count: labels.length, labels, unavailable};
}
