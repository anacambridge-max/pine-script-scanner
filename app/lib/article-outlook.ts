import { MarketContextRow, sectorSupport } from "./market-context";

type PreMarket = {symbol: string; snapshot_time: string; movement_direction: string; movement_score: number; aligned_snapshots: number};
type Signal = {symbol: string; signal_type: string; signal_state: string | null; signal_time: string | null; score: number | null; metadata?: {sector_rank_type?: string; movement_evidence?: {confirmed_at: string; observed_at: string; oi?: {label?: string}; news?: {impact: string; published_at: string}[]}}};
export type ArticleOutlook = {symbol: string; direction: "BUY" | "SELL" | null; score: number; clues: string[]; missing: string[]; confirmed: boolean; sources: string[]; articles: {title: string; url: string}[]};

const istDay = (value: string | number) => new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Kolkata"}).format(new Date(value));
const valid = (value: string | undefined | null) => value ? Date.parse(value) : NaN;
const positiveOI = new Set(["LONG BUILDUP", "SHORT COVERING"]);
const negativeOI = new Set(["SHORT BUILDUP", "LONG UNWINDING"]);

function articleTone(context: string | undefined): "BUY" | "SELL" | null {
  const text = context?.toLowerCase() ?? "";
  if (!text || text.length > 400 || /results? today|earnings (?:on|today)|will (?:announce|release|post)/.test(text)) return null;
  const positive = /profit (?:rose|rises|grew|jumps|surges|soars)|order win|won (?:an? )?order|contract win|approval|approved|revenue (?:rose|rises|grew|jumps|surges)/.test(text);
  const negative = /profit (?:fell|falls|declines|drops|plunges)|loss (?:widens|rises)|revenue (?:fell|falls|declines|drops|plunges)/.test(text);
  return positive === negative ? null : positive ? "BUY" : "SELL";
}

function openingDirection(row: MarketContextRow): "BUY" | "SELL" | null {
  const o = row.market_evidence.opening;
  if (o?.status !== "READY" || o.open == null || o.close == null || o.move_pct == null ||
      o.volume_multiple == null || o.body_ratio == null || o.close_location == null ||
      o.volume_multiple < 3 || o.body_ratio < .35 || Math.abs(o.move_pct) < .5) return null;
  if (o.close > o.open && o.move_pct > 0 && o.close_location >= .7) return "BUY";
  if (o.close < o.open && o.move_pct < 0 && o.close_location <= .3) return "SELL";
  return null;
}

export function rankArticleOutlooks(rows: MarketContextRow[], preMarket: PreMarket[], signals: Signal[], now = new Date()): ArticleOutlook[] {
  const day = istDay(now.getTime());
  const preBySymbol = new Map(preMarket.filter(p => istDay(p.snapshot_time) === day).map(p => [p.symbol, p]));
  const signalsBySymbol = new Map<string, Signal>();
  for (const signal of signals) {
    if (signal.signal_state !== "CONFIRMED" || !signal.signal_time || istDay(signal.signal_time) !== day) continue;
    const prior = signalsBySymbol.get(signal.symbol);
    if (!prior || valid(signal.signal_time) > valid(prior.signal_time)) signalsBySymbol.set(signal.symbol, signal);
  }
  const out: ArticleOutlook[] = [];
  for (const row of rows) {
    const articles = (row.market_evidence.daily_articles ?? []).filter(a =>
      istDay(a.published_at) === day && valid(a.published_at) <= now.getTime());
    if (!articles.length || istDay(row.observed_at) !== day) continue;
    const signal = signalsBySymbol.get(row.symbol);
    const cutoff = signal ? valid(signal.metadata?.movement_evidence?.confirmed_at) || valid(signal.signal_time) + 180000 : now.getTime();
    const eligible = articles.filter(a => valid(a.published_at) <= cutoff);
    const pre = preBySymbol.get(row.symbol);
    const preDirection = pre?.movement_direction === "UP WATCH" ? "BUY" : pre?.movement_direction === "DOWN WATCH" ? "SELL" : null;
    const openingTime = row.market_evidence.opening?.timestamp;
    const openDirection = openingTime && istDay(openingTime) === day ? openingDirection(row) : null;
    const liveOiTime = valid(row.market_evidence.oi?.quote_time);
    const liveOiFresh = Number.isFinite(liveOiTime) && liveOiTime <= now.getTime() && now.getTime() - liveOiTime <= 180000;
    const oiLabel = signal?.metadata?.movement_evidence?.oi?.label ?? (!signal && liveOiFresh ? row.market_evidence.oi?.label : null);
    const oiDirection = positiveOI.has(oiLabel ?? "") ? "BUY" : negativeOI.has(oiLabel ?? "") ? "SELL" : null;
    const toneDirections = new Set(eligible.map(a => articleTone(a.context)).filter(Boolean));
    const newsDirection = toneDirections.size === 1 ? [...toneDirections][0] : null;
    const direction = signal?.signal_type === "BUY" || signal?.signal_type === "SELL" ? signal.signal_type :
      openDirection && (!preDirection || preDirection === openDirection) ? openDirection :
      preDirection && (pre?.aligned_snapshots ?? 0) >= 2 && (oiDirection === preDirection || newsDirection === preDirection) ? preDirection : null;
    const clues: string[] = [];
    const missing: string[] = [];
    if (direction && preDirection === direction && pre && pre.aligned_snapshots >= 2 && valid(pre.snapshot_time) <= cutoff) clues.push("Pre-market aligned");
    else missing.push("Pre-market");
    const openingAt = valid(row.market_evidence.opening?.timestamp);
    if (direction && openDirection === direction && Number.isFinite(openingAt) && openingAt + 60000 <= cutoff) {
      clues.push(`Opening ${row.market_evidence.opening?.volume_multiple?.toFixed(1)}× volume`);
    } else missing.push("Opening");
    const atSignal = signal?.metadata?.sector_rank_type;
    const sector = direction && (atSignal === (direction === "BUY" ? "TOP 3 GAINER" : "TOP 3 LOSER") ||
      (!signal && sectorSupport(row.sector_context, direction, now).bonus > 0));
    if (sector) clues.push(direction === "BUY" ? "Sector top gainer" : "Sector top loser");
    else missing.push("Sector");
    const evidence = signal?.metadata?.movement_evidence;
    const observed = valid(evidence?.observed_at);
    const evidenceFresh = !signal || Number.isFinite(observed) && observed <= cutoff && cutoff - observed <= 180000;
    const oiAligned = Boolean(direction && evidenceFresh && oiDirection === direction);
    const contextNews = evidence?.news ?? row.market_evidence.news;
    const verifiedNews = Boolean(direction && evidenceFresh && contextNews.some(n => valid(n.published_at) <= cutoff &&
      istDay(n.published_at) === day && (direction === "BUY" ? /BULLISH|POSITIVE/i : /BEARISH|NEGATIVE/i).test(n.impact)));
    if (direction && (oiAligned || verifiedNews || newsDirection === direction)) clues.push([oiAligned && "OI", verifiedNews && "News", newsDirection === direction && "Article catalyst"].filter(Boolean).join(" + "));
    else missing.push("News/OI");
    // A publisher mention by itself never determines direction or creates a signal.
    out.push({symbol: row.symbol, direction: !signal && clues.length < 2 ? null : direction, score: clues.length, clues, missing, confirmed: Boolean(signal),
      sources: [...new Set(articles.map(a => a.source))], articles: articles.map(a => ({title: a.title, url: a.url}))});
  }
  return out.sort((a,b) => Number(b.confirmed) - Number(a.confirmed) || b.score - a.score || a.symbol.localeCompare(b.symbol));
}
