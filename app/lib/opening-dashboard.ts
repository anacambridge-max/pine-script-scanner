import type { MarketContextRow } from './market-context';
import { latestFiling, sectorSupport } from './market-context';

export type OpeningLeader = {
  symbol: string; direction: 'UP WATCH' | 'DOWN WATCH'; tier: 'EXPLOSIVE' | 'STRONG' | 'SPURT';
  score: number; volumeMultiple: number; gapPct: number; movePct: number; bodyRatio: number;
  closeLocation: number; sectorLabel: string | null; confirmed: boolean; reasons: string[]; openingCloseAt: string;
};

type SignalLink = {symbol: string; signal_type: string; signal_state: string | null};
type PreMarketLink = {symbol: string; movement_direction: string};
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const istDay = (value: Date) => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Kolkata'}).format(value);
const activeSession = (now: Date) => {
  const parts = new Intl.DateTimeFormat('en-GB', {timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(now).split(':').map(Number);
  const minute = parts[0] * 60 + parts[1];
  return minute >= 9 * 60 + 15 && minute < 15 * 60 + 30;
};

export function selectOpeningLeaders(rows: MarketContextRow[], signals: SignalLink[], premarket: PreMarketLink[], now = new Date()): OpeningLeader[] {
  const confirmed = new Set(signals.filter(signal => signal.signal_state === 'CONFIRMED').map(signal => `${signal.symbol}|${signal.signal_type}`));
  const premarketDirections = new Set(premarket.map(row => `${row.symbol}|${row.movement_direction}`));
  const result: OpeningLeader[] = [];
  for (const row of rows) {
    const bar = row.market_evidence?.opening;
    if (bar?.status !== 'READY' || !bar.timestamp || istDay(new Date(bar.timestamp)) !== istDay(now) ||
        !finite(bar.open) || !finite(bar.close) || !finite(bar.gap_pct) || !finite(bar.move_pct) ||
        !finite(bar.body_ratio) || !finite(bar.close_location) || !finite(bar.volume_multiple)) continue;
    const up = bar.close > bar.open && bar.move_pct > 0;
    const down = bar.close < bar.open && bar.move_pct < 0;
    if (!up && !down) continue;
    const direction = up ? 'UP WATCH' : 'DOWN WATCH';
    const location = up ? bar.close_location : 1 - bar.close_location;
    const volume = bar.volume_multiple;
    // A large opening gap can produce a moderate body even when volume and
    // the final close show real participation. Keep it as a watch candidate.
    const gapDriven = Math.abs(bar.gap_pct) >= 2 && Math.sign(bar.gap_pct) === (up ? 1 : -1) &&
      volume >= 10 && bar.body_ratio >= .3 && location >= .65;
    if (volume < 3 || Math.abs(bar.move_pct) < .5 ||
        !gapDriven && (bar.body_ratio < .35 || location < .7)) continue;
    const sector = sectorSupport(row.sector_context, direction, now);
    const alignedPreMarket = premarketDirections.has(`${row.symbol}|${direction}`);
    const confirmedSignal = confirmed.has(`${row.symbol}|${up ? 'BUY' : 'SELL'}`);
    const compression = row.daily_context?.status === 'READY' && Boolean(row.daily_context.compression);
    const openingClose = Date.parse(bar.timestamp) + 60000;
    const filing = latestFiling(row.market_evidence.filings, new Date(openingClose).toISOString());
    const freshNews = (row.market_evidence.news || []).some(news => {
      const published = Date.parse(news.published_at);
      return Number.isFinite(published) && published <= openingClose && istDay(new Date(published)) === istDay(now);
    });
    const score = Math.min(100, Math.round(
      Math.min(30, volume * 2.5) + Math.min(20, bar.body_ratio * 25) +
      Math.min(15, location * 15) + Math.min(10, Math.abs(bar.move_pct) * 4) +
      sector.bonus + (alignedPreMarket ? 5 : 0) + (compression ? 5 : 0) + (freshNews ? 5 : 0) + (filing ? 4 : 0)
    ));
    const tier = volume >= 10 && bar.body_ratio >= .55 && location >= .8 || gapDriven && volume >= 15 ? 'EXPLOSIVE' :
      volume >= 6 && bar.body_ratio >= .5 ? 'STRONG' : 'SPURT';
    const reasons = [
      `${volume.toFixed(1)}× opening volume`,
      `${Math.round(bar.body_ratio * 100)}% body`,
      alignedPreMarket ? 'Pre-market aligned' : null,
      gapDriven ? 'Gap-led opening volume' : null,
      compression ? 'Prior-day compression' : null,
      freshNews ? 'Fresh headline' : null,
      filing ? `NSE filing · ${filing.period === 'SAME DAY' ? 'Today' : 'Previous session'}` : null,
    ].filter(Boolean) as string[];
    result.push({symbol: row.symbol, direction, tier, score, volumeMultiple: volume,
      gapPct: bar.gap_pct, movePct: bar.move_pct, bodyRatio: bar.body_ratio,
      closeLocation: location, sectorLabel: sector.bonus ? sector.label : null,
      confirmed: confirmedSignal, reasons, openingCloseAt: new Date(openingClose).toISOString()});
  }
  return result.sort((a,b) => b.score-a.score || b.volumeMultiple-a.volumeMultiple || a.symbol.localeCompare(b.symbol)).slice(0, 18);
}

export function marketBreadth(rows: MarketContextRow[], universe: number, now = new Date()) {
  let advances = 0, declines = 0, unchanged = 0;
  for (const row of rows) {
    const candle = row.market_evidence?.candle;
    const observed = Date.parse(row.observed_at);
    if (candle?.status !== 'READY' || !finite(candle.change_pct) || !Number.isFinite(observed) ||
        istDay(new Date(observed)) !== istDay(now) ||
        activeSession(now) && (observed > now.getTime() + 5000 || now.getTime() - observed > 180000)) continue;
    if (candle.change_pct > .05) advances++;
    else if (candle.change_pct < -.05) declines++;
    else unchanged++;
  }
  const covered = advances + declines + unchanged;
  return {advances, declines, unchanged, covered, universe,
    ratio: declines ? advances / declines : advances ? null : 0,
    label: covered === 0 && rows.length > 0 ? 'QUOTES STALE' : covered < Math.max(20, universe * .7) ? 'PARTIAL COVERAGE' : advances > declines * 1.5 ? 'BROAD ADVANCE' : declines > advances * 1.5 ? 'BROAD DECLINE' : 'MIXED BREADTH'};
}

export function sectorRotation(rows: MarketContextRow[], now = new Date()) {
  const sectors = new Map<string, {sector: string; change: number; observedAt: string}>();
  for (const row of rows) {
    const data = row.sector_context;
    if (!data?.sector || !finite(data.sector_change) || !data.sector_observed_at ||
        sectorSupport(data, 'UP WATCH', now).label === 'Sector data stale' ||
        sectorSupport(data, 'UP WATCH', now).label === 'Sector data unavailable') continue;
    const prior = sectors.get(data.sector);
    if (!prior || Date.parse(data.sector_observed_at) > Date.parse(prior.observedAt))
      sectors.set(data.sector, {sector: data.sector, change: data.sector_change, observedAt: data.sector_observed_at});
  }
  return [...sectors.values()].sort((a,b) => b.change-a.change);
}
