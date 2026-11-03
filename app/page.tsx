'use client'

import { useEffect, useMemo, useState } from "react";
import { DailyContext, MarketContextRow, MovementEvidence, PatternFilter, sectorSupport, confirmedPatternHint, matchesPatternFilter, latestDailyArticle } from "./lib/market-context";
import { selectionRules, compareSelections } from "./lib/trade-selection";
import { buildCommonStockRows } from "./lib/cross-section";
import { marketBreadth, sectorRotation, selectOpeningLeaders } from "./lib/opening-dashboard";
import { signalAlignment } from "./lib/signal-alignment";

type HotStock = {
  id: string; trade_date: string; symbol: string; company_name: string | null;
  score: number; technical_score: number; news_score: number; close: number | null;
  change_percent: number | null; volume_multiple: number | null; body_ratio: number | null;
  compression_score: number | null; range_expansion: number | null; breakout_proximity: number | null;
  news_impact: string | null; news_summary: string | null;
  news_source?: string | null; published_ist?: string | null; direction?: string | null;
  news_titles: Array<{title:string;url:string;impact:string}>;
  reasons: string[]; setup: string | null;
};

type PreMarketRow = {
  id: string; snapshot_time: string; symbol: string;
  previous_close: number | null; indicative_price: number | null;
  indicative_gap_pct: number | null; indicative_tradable_qty: number | null;
  buy_qty: number | null; sell_qty: number | null; imbalance_qty: number | null;
  oi_change_pct: number | null; oi_volume: number | null;
  preopen_score: number; preopen_bias: string; reasons: string[];
  source_preopen?: string | null; source_oi?: string | null;
  movement_direction: "UP WATCH" | "DOWN WATCH"; movement_score: number;
  aligned_snapshots: number; observed_snapshots: number;
};

type Signal = {
  id: string; symbol: string; instrument_key: string | null; signal_type: string;
  signal_state: string | null; score: number | null; grade: string | null;
  ltp: number | null; change_percent: number | null; entry: number | null;
  stop_loss: number | null; target1: number | null; target2: number | null;
  risk_reward: number | null; setup: string | null; cash_trend: string | null;
  futures_trend: string | null; oi_setup: string | null; ema20_status: string | null;
  vwap_status: string | null; rvol: number | null; volume_grade: string | null;
  breakout_level: number | null; fo_confirmation: string | null;
  is_active: boolean | null; signal_time: string | null; last_updated: string | null;
  metadata?: { timeframe?: string; company_name?: string; sector?: string; sector_change_percent?: number; sector_rank?: number; sector_rank_type?: string; score_breakdown?: Record<string, unknown>; outcome?: {version?:number}; daily_context?: DailyContext; movement_evidence?: MovementEvidence; opening_candle?: {is_opening?: boolean}; full_result?: {timestamp?: string; body_ratio?: number; close_location?: number; range_expansion?: number} };
};

const fmt = (value: number | null, digits = 2) =>
  value === null || value === undefined || Number.isNaN(Number(value)) ? "—" : Number(value).toFixed(digits);

const timeFmt = (value: string | null) =>
  value ? new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value)) : "—";

const signalClock = (signal: Signal) =>
  timeFmt(signal.signal_time);

export default function Home() {
  type SortKey = "alignment" | "pattern" | "signal_time" | "symbol" | "signal_type" | "timeframe" | "score" | "grade" | "sector" | "sector_rank" | "ltp" | "entry" | "stop_loss" | "target1" | "target2" | "risk_reward" | "rvol" | "breakout_level" | "setup";
  const [signals, setSignals] = useState<Signal[]>([]);
  const [marketContext, setMarketContext] = useState<MarketContextRow[]>([]);
  const [contextError, setContextError] = useState("");
  const contextBySymbol = useMemo(() => new Map(marketContext.map(row => [row.symbol, row])), [marketContext]);
  const sectorBadge = (symbol: string, direction: string) => {
    const context = contextBySymbol.get(symbol)?.sector_context;
    const support = sectorSupport(context, direction);
    return <small className={support.bonus ? "sectorSupport supported" : "sectorSupport"} title={context?.sector_observed_at ? `Sector snapshot ${timeFmt(context.sector_observed_at)} IST` : ""}>{support.label}</small>;
  };
  const articleBadge = (symbol: string, cutoff: string | null | undefined) => {
    const article = latestDailyArticle(contextBySymbol.get(symbol)?.market_evidence.daily_articles, cutoff);
    return article ? <a className="filingTag" href={article.url} target="_blank" rel="noreferrer" title={article.title + " · " + article.source + " · " + article.kind + " · market context only"}>📰 {article.source.toUpperCase()} · {article.kind === "EARNINGS / RESULTS" ? "RESULTS" : "WATCHLIST"}</a> : null;
  };
  const patternBadge = (signal: Signal) => {
    const hint = confirmedPatternHint(signal, contextBySymbol.get(signal.symbol)?.daily_context);
    return <>{hint.labels.length > 0 && <small className="sectorSupport">{hint.labels.join(" · ")}</small>}{hint.label && <small className="sectorSupport supported" title={hint.reason ?? ""}>{hint.label}</small>}{hint.label && hint.supporting.length > 0 && <small className="sectorSupport">{hint.supporting.join(" · ")}</small>}</>;
  };
  async function loadMarketContext() {
    try {
      const response = await fetch("/api/market-context", {cache: "no-store"});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Market context unavailable");
      setMarketContext(payload.rows ?? []);
      setContextError("");
    } catch (err) {
      setContextError(err instanceof Error ? err.message : "Market context could not refresh");
      setMarketContext([]);
    }
  }
  const [hotStocks, setHotStocks] = useState<HotStock[]>([]);
  const [technicalOnlyRows, setTechnicalOnlyRows] = useState<HotStock[]>([]);
  const [preMarketRows, setPreMarketRows] = useState<PreMarketRow[]>([]);
  const rankedPreMarketRows = [...preMarketRows].sort((a,b) =>
    (b.movement_score * 0.9 + sectorSupport(contextBySymbol.get(b.symbol)?.sector_context, b.movement_direction).bonus + (latestDailyArticle(contextBySymbol.get(b.symbol)?.market_evidence.daily_articles, b.snapshot_time) ? 4 : 0)) -
    (a.movement_score * 0.9 + sectorSupport(contextBySymbol.get(a.symbol)?.sector_context, a.movement_direction).bonus + (latestDailyArticle(contextBySymbol.get(a.symbol)?.market_evidence.daily_articles, a.snapshot_time) ? 4 : 0)));
  const [preMarketSourceCount, setPreMarketSourceCount] = useState(0);
  const [preMarketSnapshotTime, setPreMarketSnapshotTime] = useState<string | null>(null);
  const [preMarketSnapshotCount, setPreMarketSnapshotCount] = useState(0);
  const [preMarketStudyComplete, setPreMarketStudyComplete] = useState(false);
  const [preMarketWindowStart, setPreMarketWindowStart] = useState<string | null>(null);
  const [preMarketWindowEnd, setPreMarketWindowEnd] = useState<string | null>(null);
  const [filter, setFilter] = useState<"ALL" | "BUY" | "SELL">("ALL");
  const [patternFilter, setPatternFilter] = useState<PatternFilter>("ALL");
  const patternOptions: {value: PatternFilter; label: string}[] = [
    {value: "STRONG", label: "Strong combined setups"},
    {value: "MOVERS", label: "All potential movers"},
    {value: "GAINERS", label: "Potential gainers"},
    {value: "LOSERS", label: "Potential losers"},
    {value: "SUPPORTED", label: "Movers + OI/news support"},
    {value: "NR7", label: "NR7"}, {value: "NR4", label: "NR4"},
    {value: "NARROW", label: "Narrow PD range"}, {value: "ALL", label: "All confirmed signals"},
  ];
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [hotError, setHotError] = useState("");
  const [preMarketError, setPreMarketError] = useState("");
  const [health, setHealth] = useState<{status: string; last_run_at: string | null; universe_count: number}>({status: "CHECKING", last_run_at: null, universe_count: 0});
  const [performance, setPerformance] = useState<{tracked:number; complete:number; pending:number; firstHit:{target:number;stop:number;ambiguous:number;neither:number}; medianReturnPct:Record<string,number|null>; scoreBands:Array<{label:string;sample:number;medianReturn60Pct:number|null}>; sufficientSample:boolean} | null>(null);

  async function loadPerformance() {
    try {
      const response = await fetch("/api/performance", { cache: "no-store" });
      if (response.ok) setPerformance(await response.json());
    } catch { /* The scanner remains usable while measurement is unavailable. */ }
  }

  async function loadHealth() {
    try {
      const response = await fetch("/api/health", { cache: "no-store" });
      const payload = await response.json();
      setHealth({status: payload.status || "UNAVAILABLE", last_run_at: payload.last_run_at ?? null, universe_count: Number(payload.universe_count || 0)});
    } catch {
      setHealth({status: "UNAVAILABLE", last_run_at: null, universe_count: 0});
    }
  }
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [sort, setSort] = useState<{key: SortKey; dir: "asc" | "desc"}>({ key: "signal_time", dir: "desc" });
  const openingLeaders = useMemo(() => selectOpeningLeaders(marketContext, signals, preMarketRows), [marketContext, signals, preMarketRows]);
  const alignmentFor = (signal: Signal) => signalAlignment(signal, preMarketRows, contextBySymbol.get(signal.symbol));
  const breadth = useMemo(() => marketBreadth(marketContext, health.universe_count || marketContext.length), [marketContext, health.universe_count]);
  const rotatingSectors = useMemo(() => sectorRotation(marketContext), [marketContext]);
  const dailyArticles = useMemo(() => {
    const now = Date.now();
    const seen = new Set<string>();
    return marketContext.flatMap(row => (row.market_evidence?.daily_articles ?? []).map(article => ({symbol: row.symbol, article})))
      .filter(({article}) => Date.parse(article.published_at) <= now && Date.parse(article.published_at) >= now - 24 * 60 * 60 * 1000)
      .filter(({symbol, article}) => { const key = `${symbol}|${article.url}|${article.kind}`; if (seen.has(key)) return false; seen.add(key); return true; })
      .sort((a,b) => Number(b.article.kind === "EARNINGS / RESULTS") - Number(a.article.kind === "EARNINGS / RESULTS") || Date.parse(b.article.published_at) - Date.parse(a.article.published_at))
      .slice(0, 24);
  }, [marketContext]);

  async function loadHotStocks() {
    try {
      const response = await fetch("/api/hot-stocks", { cache: "no-store" });
      const payload = await response.json();
      if (response.ok) {
        setHotError(payload.warning || "");
        setHotStocks(payload.rows ?? []);
        setTechnicalOnlyRows(payload.technical_only_rows ?? []);
      } else {
        setHotError(payload.error || "Unable to load morning watchlists");
      }
    } catch {
      setHotError("Morning watchlists could not refresh; displayed rows may be stale.");
    }
  }

  async function loadPreMarketStudy() {
    try {
      const response = await fetch("/api/pre-market-study", { cache: "no-store" });
      const payload = await response.json();
      if (response.ok) {
        setPreMarketError("");
        setPreMarketRows(payload.rows ?? []);
        setPreMarketSourceCount(Number(payload.source_symbol_count ?? 0));
        setPreMarketSnapshotTime(payload.snapshot_time ?? null);
        setPreMarketSnapshotCount(Number(payload.snapshot_count ?? 0));
        setPreMarketStudyComplete(Boolean(payload.study_complete));
        setPreMarketWindowStart(payload.window_start ?? null);
        setPreMarketWindowEnd(payload.window_end ?? null);
      } else {
        setPreMarketError(payload.error || "Unable to load NSE pre-market study");
      }
    } catch {
      setPreMarketError("NSE study could not refresh; displayed rows may be stale.");
    }
  }

  async function loadSignals() {
    try {
      const response = await fetch("/api/signals?limit=500", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Unable to load signals");
      setSignals(payload.signals ?? []);
      setLastRefresh(new Date());
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load signals");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSignals();
    loadHealth();
    loadHotStocks();
    loadPreMarketStudy();
    loadMarketContext();
    loadPerformance();
    const timer = window.setInterval(loadSignals, 5000);
    const healthTimer = window.setInterval(loadHealth, 15000);
    const hotTimer = window.setInterval(loadHotStocks, 30000);
    const preMarketTimer = window.setInterval(loadPreMarketStudy, 30000);
    const contextTimer = window.setInterval(loadMarketContext, 30000);
    const performanceTimer = window.setInterval(loadPerformance, 60000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(healthTimer);
      window.clearInterval(hotTimer);
      window.clearInterval(preMarketTimer);
      window.clearInterval(contextTimer);
      window.clearInterval(performanceTimer);
    };
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toUpperCase();
    const rows = signals.filter((signal) => {
      const sideOk = filter === "ALL" || signal.signal_type.toUpperCase().includes(filter);
      const haystack = [signal.symbol, signal.metadata?.company_name, signal.metadata?.sector, signal.setup].filter(Boolean).join(" ").toUpperCase();
      return sideOk && matchesPatternFilter(signal, contextBySymbol.get(signal.symbol)?.daily_context, patternFilter) && (!q || haystack.includes(q));
    });

    return rows.sort((x, y) => {
      const value = (s: Signal): string | number => {
        switch (sort.key) {
          case "signal_time": return s.signal_time ? new Date(s.signal_time).getTime() : 0;
          case "symbol": return s.symbol;
          case "pattern": { const hint = confirmedPatternHint(s, contextBySymbol.get(s.symbol)?.daily_context); return [...hint.labels, hint.label ?? ""].join(" "); }
          case "alignment": return alignmentFor(s).count;
          case "signal_type": return s.signal_type;
          case "timeframe": return Number(s.metadata?.timeframe ?? 0);
          case "sector": return s.metadata?.sector ?? "";
          case "sector_rank": return s.metadata?.sector_rank ?? 999;
          case "grade": return s.grade ?? "";
          case "setup": return s.setup ?? "";
          default: return Number(s[sort.key] ?? -Infinity);
        }
      };
      const av = value(x), bv = value(y);
      const cmp = typeof av === "string" && typeof bv === "string"
        ? av.localeCompare(bv)
        : Number(av) - Number(bv);
      return sort.dir === "asc" ? cmp : -cmp;
    });
  }, [signals, filter, search, sort, marketContext, preMarketRows, patternFilter]);

  const setSortKey = (key: SortKey) => {
    setSort((current) => current.key === key
      ? { key, dir: current.dir === "asc" ? "desc" : "asc" }
      : { key, dir: key === "signal_time" ? "desc" : "desc" });
  };

  const buys = signals.filter((s) => s.signal_type.toUpperCase().includes("BUY")).length;
  const sells = signals.filter((s) => s.signal_type.toUpperCase().includes("SELL")).length;
  const avgScore = signals.length ? Math.round(signals.reduce((sum, s) => sum + Number(s.score || 0), 0) / signals.length) : 0;
  const topSector = [...signals].filter(s => s.metadata?.sector).sort((a,b) => Number(b.score||0)-Number(a.score||0))[0]?.metadata?.sector;
  const newsBySymbol = useMemo(() => new Map(hotStocks
    .filter(row => row.news_score > 0 && row.published_ist && row.news_summary)
    .map(row => [row.symbol.trim().toUpperCase(), row])), [hotStocks]);


  const preMarketConfirmedRows = useMemo(() => {
    const premarketBySymbol = new Map<string, PreMarketRow>();
    for (const row of preMarketRows) {
      const symbol = String(row.symbol || "").trim().toUpperCase();
      if (symbol && !premarketBySymbol.has(symbol)) {
        premarketBySymbol.set(symbol, row);
      }
    }
    return signals
      .filter(signal => signal.signal_state === "CONFIRMED")
      .filter(signal => premarketBySymbol.has(String(signal.symbol || "").trim().toUpperCase()))
      .filter(signal => {
        const candidate = premarketBySymbol.get(String(signal.symbol || "").trim().toUpperCase())!;
        return candidate.movement_direction === "UP WATCH"
          ? signal.signal_type.toUpperCase().includes("BUY")
          : signal.signal_type.toUpperCase().includes("SELL");
      })
      .map(signal => ({
        signal,
        premarket: premarketBySymbol.get(String(signal.symbol || "").trim().toUpperCase())!,
      }))
      .sort((a, b) => Number(b.signal.score || 0) - Number(a.signal.score || 0));
  }, [preMarketRows, signals]);

  const selectorRows = filtered
    .filter(s => s.signal_state === "CONFIRMED" && ["BUY", "SELL"].includes(s.signal_type))
    .map(signal => ({signal, ...selectionRules(signal, contextBySymbol.get(signal.symbol)?.daily_context)}));

  const compareAlignedSelections = (a: typeof selectorRows[number], b: typeof selectorRows[number]) =>
    alignmentFor(b.signal).count - alignmentFor(a.signal).count || compareSelections(a, b);
  const topBuys = selectorRows.filter(x => x.signal.signal_type === "BUY").sort(compareAlignedSelections).slice(0, 10);
  const topSells = selectorRows.filter(x => x.signal.signal_type === "SELL").sort(compareAlignedSelections).slice(0, 10);

  const commonStockRows = useMemo(() => buildCommonStockRows(signals, [
    {name: "PRE-MARKET MOVEMENT WATCH", symbols: preMarketRows.map(row => row.symbol)},
    {name: "PRE-MARKET × ALIGNED CONFIRMED", symbols: preMarketConfirmedRows.map(row => row.signal.symbol)},
    {name: "TODAY'S HOT STOCKS", symbols: hotStocks.map(row => row.symbol)},
    {name: "TECHNICAL ONLY", symbols: technicalOnlyRows.map(row => row.symbol)},
    {name: "TOP BUY CANDIDATES", symbols: topBuys.map(row => row.signal.symbol)},
    {name: "TOP SELL CANDIDATES", symbols: topSells.map(row => row.signal.symbol)},
  ]), [signals, preMarketRows, preMarketConfirmedRows, hotStocks, technicalOnlyRows, topBuys, topSells]);

  const columns: { key: SortKey; label: string; align?: "right" }[] = [
    { key: "signal_time", label: "TIME" },
    { key: "symbol", label: "SYMBOL" },
    { key: "pattern", label: "PATTERN / POTENTIAL MOVE" },
    { key: "alignment", label: "CLUES" },
    { key: "signal_type", label: "SIGNAL" },
    { key: "score", label: "SCORE", align: "right" },
    { key: "ltp", label: "SIGNAL CLOSE", align: "right" },
    { key: "entry", label: "ENTRY", align: "right" },
    { key: "stop_loss", label: "SL", align: "right" },
    { key: "target1", label: "T1", align: "right" },
    { key: "target2", label: "T2", align: "right" },
    { key: "risk_reward", label: "R:R", align: "right" },
    { key: "rvol", label: "RVOL", align: "right" },
    { key: "breakout_level", label: "BREAKOUT", align: "right" },
    { key: "setup", label: "SETUP" },
  ];

  const sortIcon = (key: SortKey) => sort.key !== key ? "↕" : sort.dir === "asc" ? "↑" : "↓";

  return (
    <main className="page">
      <header className="header">
        <div>
          <div className="brandRow"><div className="logoMark">P</div><div><div className="eyebrow">PRIME TECHNICAL</div><h1>Live Scanner</h1></div></div>
          <p>Real-time F&O stock scanner · 3-minute confirmed PDH / PDL breaks</p>
        </div>
        <div className="headerRight"><div className="marketBadge" title={health.last_run_at ? "Worker heartbeat " + timeFmt(health.last_run_at) : "No verified worker heartbeat"}><span className="pulse" style={{background: health.status === "LIVE" ? "#25ce8d" : "#f5b85c", boxShadow: "none"}} /> {health.status === "LIVE" ? "FEED LIVE" : "WORKER " + health.status}</div><div className="refreshText">Auto refresh <b>5s</b></div></div>
      </header>

      <section className="cards">
        <div className="card"><div className="cardTop"><span>CONFIRMED TODAY</span><span className="miniIcon">◷</span></div><strong>{signals.length}</strong><small>3-minute signals</small></div>
        <div className="card buy"><div className="cardTop"><span>BUY CONFIRMED</span><span className="miniIcon">↗</span></div><strong>{buys}</strong><small>PDH close-break</small></div>
        <div className="card sell"><div className="cardTop"><span>SELL CONFIRMED</span><span className="miniIcon">↘</span></div><strong>{sells}</strong><small>PDL close-break</small></div>
        <div className="card"><div className="cardTop"><span>AVG SCORE</span><span className="miniIcon">★</span></div><strong>{avgScore}</strong><small>{topSector ? `Top signal sector: ${topSector}` : "Waiting for sector data"}</small></div>
      </section>

      <section className="openingDesk" aria-label="One-minute opening leaders and market breadth">
        <div className="openingHead"><div><span className="deskKicker">OPENING ACTIVITY · 09:15 IST</span><h2>Daily movement shortlist</h2><p>Completed 1-minute candle, volume versus the previous session’s first 15 minutes, price action and sector context. Watch candidates only; confirmed signals stay separate.</p></div><span className="openingCount">{openingLeaders.length} selected</span></div>
        <div className="openingContext">
          <div className="breadthCard"><div className="openingContextTitle">MARKET BREADTH <span>{breadth.label}</span></div><div className="breadthNumbers"><b className="up">{breadth.advances}<small>UP</small></b><b>{breadth.unchanged}<small>FLAT</small></b><b className="down">{breadth.declines}<small>DOWN</small></b><b>{breadth.ratio == null ? "—" : fmt(breadth.ratio)}<small>A:D</small></b></div><div className="breadthBar"><i style={{width: breadth.covered ? `${breadth.advances / breadth.covered * 100}%` : "0%"}} /><em style={{width: breadth.covered ? `${breadth.declines / breadth.covered * 100}%` : "0%"}} /></div><small className="openingNote">{breadth.covered}/{breadth.universe || "—"} F&amp;O stocks with today’s quote · partial coverage is marked above</small></div>
          <div className="rotationCard"><div className="openingContextTitle">SECTOR ROTATION <span>{rotatingSectors.length} mapped sectors</span></div>{rotatingSectors.length ? rotatingSectors.slice(0, 5).map((sector, index) => <div className="rotationRow" key={sector.sector}><span>{index + 1}. {sector.sector}</span><b className={sector.change >= 0 ? "up" : "down"}>{sector.change >= 0 ? "+" : ""}{fmt(sector.change)}%</b></div>) : <div className="deskEmpty">Sector quotes are not available yet.</div>}</div>
        </div>
        <div className="openingColumns">{(["EXPLOSIVE", "STRONG", "SPURT"] as const).map(tier => <div className="openingColumn" key={tier}><div className={`openingColumnTitle ${tier.toLowerCase()}`}>{tier}<span>{openingLeaders.filter(row => row.tier === tier).length}</span></div>{openingLeaders.filter(row => row.tier === tier).map(row => <div className="openingItem" key={row.symbol}><div className="openingItemTop"><strong>{row.symbol}</strong><b className={row.direction === "UP WATCH" ? "up" : "down"}>{row.direction === "UP WATCH" ? "↑" : "↓"} {row.score}</b></div><div className="openingItemTags"><span>{row.volumeMultiple.toFixed(1)}× volume</span><span>{row.direction}</span><span>Gap {row.gapPct >= 0 ? "+" : ""}{fmt(row.gapPct)}%</span></div><p>{row.reasons.slice(1).join(" · ")}</p>{row.sectorLabel && <small className="openingSector">{row.sectorLabel}</small>}{articleBadge(row.symbol, row.openingCloseAt)}{row.confirmed && <small className="openingConfirmed">3M {row.direction === "UP WATCH" ? "BUY" : "SELL"} CONFIRMED</small>}</div>)}{openingLeaders.every(row => row.tier !== tier) && <div className="deskEmpty">No qualified stocks in this tier.</div>}</div>)}</div>
        <small className="openingNote openingFooter">Minimum: 3× relative opening volume, 35% candle body, directional close near the candle edge and 0.5% move from previous close. Gap-led exception: ≥2% same-direction gap, ≥10× volume, ≥30% body and ≥65% directional close. Scores rank observed setups, not future returns. Volume alone cannot identify institutional buying.</small>
      </section>

      <section className="filingsPanel" aria-label="Daily publisher stock watch and earnings articles">
        <div className="filingsHead"><div><span className="deskKicker">SAME-DAY MARKET COVERAGE · MONEYCONTROL + UPSTOX</span><h2>Stocks to watch &amp; earnings</h2><p>Stocks mentioned in today’s watchlist articles and Moneycontrol results coverage. Publisher coverage is context only; it does not confirm direction or create a signal.</p></div><span className="filingsCount">{dailyArticles.length} mentions</span></div>
        {dailyArticles.length ? <div className="filingsGrid">{dailyArticles.map(({symbol, article}, index) => <article className="filingCard" key={`${symbol}-${article.url}-${index}`}>
          <div className="filingCardTop"><strong>{symbol}</strong><span>{article.source.toUpperCase()}</span></div>
          <div className="filingBadges"><b>{article.kind}</b><span>CONTEXT · NOT A SIGNAL</span></div>
          <p className="filingSummary">{article.context || article.title}</p>
          <details className="filingDetails"><summary>Article headline</summary><p>{article.title}</p></details>
          <div className="filingCardFooter"><small>Today · {timeFmt(article.published_at)} IST</small><a href={article.url} target="_blank" rel="noreferrer">Open article ↗</a></div>
        </article>)}</div> : <div className="filingsEmpty">No same-day stock-watch or Moneycontrol earnings article has matched the scanner universe yet. The worker checks publisher pages every 15 minutes.</div>}
      </section>

      <section className="desk" aria-label="Scanner decision overview">
        <div className="deskHead"><div><span className="deskKicker">TODAY AT A GLANCE</span><h2>Movement watch & confirmations</h2><p>Pre-market rows are watch candidates. Only a completed 3-minute break is a confirmed signal.</p></div><div className={health.status === "LIVE" ? "statusChip live" : "statusChip"}>{health.status === "LIVE" ? "● LIVE WORKER" : "● WORKER " + health.status}<small>Heartbeat {timeFmt(health.last_run_at)} IST</small></div></div>
        <div className="deskGrid">
          <div className="deskPanel"><div className="deskPanelTitle">PRE-MARKET WATCH <span>{preMarketRows.length} selected</span></div>{preMarketRows.length ? rankedPreMarketRows.slice(0, 4).map(row => <div className="deskItem" key={row.id}><div><b>{row.symbol}</b>{sectorBadge(row.symbol, row.movement_direction)}{articleBadge(row.symbol, row.snapshot_time)}<small>{row.movement_direction} · {row.aligned_snapshots}/{row.observed_snapshots} aligned snapshots</small></div><strong>{fmt(row.indicative_gap_pct)}%</strong></div>) : <div className="deskEmpty">No qualified watch candidates for this session.</div>}<div className="deskFoot">NSE snapshot {timeFmt(preMarketSnapshotTime)} IST · {preMarketSnapshotCount}/9 captured{preMarketSnapshotCount > 0 && !preMarketStudyComplete ? " · incomplete" : ""} · indicative only</div></div>
          <div className="deskPanel"><div className="deskPanelTitle">ALIGNED CONFIRMATIONS <span>{preMarketConfirmedRows.length} matched</span></div>{preMarketConfirmedRows.length ? preMarketConfirmedRows.slice(0, 4).map(({signal,premarket}) => <div className="deskItem" key={signal.id}><div><b>{signal.symbol} <em className={signal.signal_type === "BUY" ? "up" : "down"}>{signal.signal_type}</em></b>{sectorBadge(signal.symbol, signal.signal_type)}{patternBadge(signal)}{articleBadge(signal.symbol, signal.signal_time)}<small>{signalClock(signal)} · pre-open {premarket.movement_direction}</small></div><strong>{fmt(signal.score,0)}</strong></div>) : <div className="deskEmpty">No pre-market candidate has an aligned confirmed signal yet.</div>}<div className="deskFoot">Agreement is context; it does not change the signal rule.</div></div>
        </div>
      </section>

      <section className="evidence" aria-label="Measured scanner outcomes"><div><span className="deskKicker">MEASURED OUTCOMES · LAST 30 DAYS</span><h2>Signal evidence</h2><p>Forward returns use completed 1-minute candles after confirmation. Scores rank setups, not win probabilities.</p></div>{performance ? <div className="evidenceStats"><div><b>{performance.complete}</b><span>complete / {performance.tracked} tracked</span></div><div><b>{performance.firstHit.target} / {performance.firstHit.stop}</b><span>target first / stop first</span></div><div><b>{performance.medianReturnPct["60"] == null ? "—" : `${performance.medianReturnPct["60"]}%`}</b><span>median 60-min directional return</span></div><div><b>{performance.firstHit.ambiguous}</b><span>ambiguous OHLC bars</span></div></div> : <div className="deskEmpty">Outcome history is not available yet.</div>}{performance && <div className="scoreBands"><b>Score bands · 60-min median</b>{performance.scoreBands.map(band => <span key={band.label}>{band.label}: {band.sample} signals · {band.medianReturn60Pct == null ? "—" : `${band.medianReturn60Pct}%`}</span>)}</div>}<small className="evidenceNote">{performance && !performance.sufficientSample ? "Small sample: wait for at least 30 completed, prospectively measured signals before judging accuracy." : "Historical rows without prospective candle tracking are excluded."}</small></section>

      <section className="toolbar">
        <div className="toolbarLeft">
          <div className="tabs">{(["ALL", "BUY", "SELL"] as const).map((item) => (
            <button key={item} className={filter === item ? "tab active" : "tab"} onClick={() => setFilter(item)}>
              {item === "ALL" ? "ALL TODAY" : item === "BUY" ? "BUY CONFIRMED" : "SELL CONFIRMED"}
            </button>
          ))}</div>
          <div className="modePill" title="New signals require strong candle, range expansion and EMA alignment. Scores are setup rankings, not win probabilities."><span className="greenDot" /> F&O · 3M · FIRST BREAK · 2× VOL</div>
        </div>
        <label className="patternFilter">Pattern filter<select aria-label="Pattern filter" value={patternFilter} onChange={event => setPatternFilter(event.target.value as PatternFilter)}>{patternOptions.map(option => <option key={option.value} value={option.value}>{option.label} ({signals.filter(signal => matchesPatternFilter(signal, contextBySymbol.get(signal.symbol)?.daily_context, option.value)).length})</option>)}</select></label>
        <label className="searchBox"><span>⌕</span><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search symbol, company or sector…" /></label>
      </section>
      <p className="filterExplanation">{filtered.length} of {signals.length} confirmed signals match{patternFilter === "STRONG" ? " · completed PDH/PDL break + compression/trend context · RVOL ≥3× · candle body ≥65% · directional close location ≥80%" : ` · ${patternOptions.find(option => option.value === patternFilter)?.label}`}. Filters narrow setup candidates; top-mover accuracy is not yet validated.</p>

      {error && <div className="error" role="alert">{error} · Displayed signals may be stale.</div>}
      {hotError && <div className="error" role="alert">{hotError}</div>}
      {preMarketError && <div className="error" role="alert">{preMarketError}</div>}
      {contextError && <div className="error" role="alert">{contextError}</div>}





      <section className="selectorWrap">
        <div className="selectorHead">
          <div>
            <strong>INTRADAY TRADE SELECTOR</strong>
            <span>Up to 10 per side from matching confirmed signals · matched clues first, then setup quality · verify current chart before entry</span>
          </div>
          <div className="selectorNote">Priority: pre-market/opening/sector/news-OI matches → candle quality → SL distance → volume</div>
        </div>

        <div className="selectorGrid">
          <div className="selectorPanel buyPanel">
            <div className="selectorPanelTitle"><span>TOP 10 BUY CANDIDATES</span><b>{topBuys.length}</b></div>
            {topBuys.length === 0 ? <div className="selectorEmpty">No BUY candidates match this filter</div> :
              topBuys.map((item, index) => (
                <div className="selectorRow" key={item.signal.id}>
                  <div className="selectorRank">{index + 1}</div>
                  <div className="selectorSymbol">
                    <strong>{item.signal.symbol}</strong>
                    {sectorBadge(item.signal.symbol, item.signal.signal_type)}{patternBadge(item.signal)}{articleBadge(item.signal.symbol, item.signal.signal_time)}
                    <small>{item.signal.metadata?.company_name ?? item.signal.symbol}</small>
                  </div>
                  <div className="selectorReasons"><span className="alignmentChip">{alignmentFor(item.signal).count}/4 clues</span>{alignmentFor(item.signal).labels.map(label => <span key={label}>{label}</span>)}{item.reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>
                  <div className="selectorScore buyScore">{item.tier}</div>
                </div>
              ))}
          </div>

          <div className="selectorPanel sellPanel">
            <div className="selectorPanelTitle"><span>TOP 10 SELL CANDIDATES</span><b>{topSells.length}</b></div>
            {topSells.length === 0 ? <div className="selectorEmpty">No SELL candidates match this filter</div> :
              topSells.map((item, index) => (
                <div className="selectorRow" key={item.signal.id}>
                  <div className="selectorRank">{index + 1}</div>
                  <div className="selectorSymbol">
                    <strong>{item.signal.symbol}</strong>
                    {sectorBadge(item.signal.symbol, item.signal.signal_type)}{patternBadge(item.signal)}{articleBadge(item.signal.symbol, item.signal.signal_time)}
                    <small>{item.signal.metadata?.company_name ?? item.signal.symbol}</small>
                  </div>
                  <div className="selectorReasons"><span className="alignmentChip">{alignmentFor(item.signal).count}/4 clues</span>{alignmentFor(item.signal).labels.map(label => <span key={label}>{label}</span>)}{item.reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>
                  <div className="selectorScore sellScore">{item.tier}</div>
                </div>
              ))}
          </div>
        </div>
      </section>

      <details className="detailGroup"><summary>Explore detailed studies <span>Hot stocks · technical watch · pre-market · cross-section</span></summary>
      <section className="watchlistWrap hotStocksWrap">
        <div className="watchlistHead">
          <div>
            <strong>TODAY'S HOT STOCKS</strong>
            <span>
              {hotStocks.length
                ? `Pre-open scan · completed ${hotStocks[0].trade_date} session + fresh Moneycontrol news · movement watchlist only · no BUY/SELL direction`
                : "Pre-open movement scanner · previous completed session + Moneycontrol catalysts · no BUY/SELL direction"}
            </span>
          </div>
          <div className="watchlistBadge">{hotStocks.length} candidates</div>
        </div>
        <div className="hotSingle">
          {hotStocks.length === 0 ? <div className="watchEmpty">No qualified news-backed candidates available. Check the worker's morning scan status.</div> :
            hotStocks.slice(0, 5).map((row, index) => (
              <div className="hotRow" key={row.id}>
                <div className="watchRank">{index + 1}</div>
                <div className="watchSymbol"><strong>{row.symbol}</strong><small>{row.company_name ?? row.symbol}</small></div>
                <div className="hotMetrics">
                  {row.change_percent != null && <span>D-1 {fmt(row.change_percent)}%</span>}
                  {row.volume_multiple != null && <span>Vol {fmt(row.volume_multiple)}×</span>}
                  <span>Tech {row.technical_score}</span>
                  <span>News {row.news_score}</span>
                  {row.news_impact && row.news_impact !== "NO MATERIAL NEWS" && <span>{row.news_impact}</span>}
                  {row.reasons.slice(0, 2).map((reason) => <span key={reason}>{reason}</span>)}
                </div>
                <div className="hotNews" title={row.news_summary ?? ""}>
                  <span>{row.news_summary ? row.news_summary : "No eligible fresh stock-specific headline"}</span>
                  {(row.news_source || row.published_ist) && <small>{row.news_source ?? "News source"}{row.published_ist ? " · " + new Date(row.published_ist).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: true }) + " IST" : ""}</small>}
                </div>
                <div className="watchScore">{row.score}</div>
              </div>
            ))}
        </div>
      </section>

      <section className="watchlistWrap hotStocksWrap">
        <div className="watchlistHead">
          <div>
            <strong>TECHNICAL-ONLY WATCH</strong>
            <span>Technical score ≥ 55 · no eligible fresh, timestamp-verified stock-specific news · watchlist only, not a BUY/SELL signal</span>
          </div>
          <div className="watchlistBadge">{technicalOnlyRows.length} candidates</div>
        </div>
        <div className="hotSingle">
          {technicalOnlyRows.length === 0 ? <div className="watchEmpty">No technical-only candidates for the latest completed session.</div> :
            technicalOnlyRows.slice(0, 5).map((row, index) => (
              <div className="hotRow" key={row.id ?? row.symbol}>
                <div className="watchRank">{index + 1}</div>
                <div className="watchSymbol"><strong>{row.symbol}</strong><small>{row.company_name ?? row.symbol}</small></div>
                <div className="hotMetrics">
                  {row.change_percent != null && <span>D-1 {fmt(row.change_percent)}%</span>}
                  {row.volume_multiple != null && <span>Vol {fmt(row.volume_multiple)}×</span>}
                  <span>Tech {row.technical_score}</span>
                  <span>News {row.news_score}</span>
                  {row.reasons.slice(0, 2).map((reason) => <span key={reason}>{reason}</span>)}
                </div>
                <div className="hotNews" title={row.news_summary ?? ""}>{row.news_summary ?? "No eligible fresh stock-specific headline"}</div>
                <div className="watchScore">{row.score}</div>
              </div>
            ))}
        </div>
      </section>

      <section className="watchlistWrap hotStocksWrap">
        <div className="watchlistHead">
          <div>
            <strong>PRE-MARKET MOVEMENT WATCH · 09:00–09:08 IST</strong>
            <span>
              {preMarketSnapshotTime
                ? `${preMarketRows.length} selected from ${preMarketSourceCount} NSE symbols · ${preMarketSnapshotCount}/9 snapshots ${preMarketStudyComplete ? "captured" : "captured; incomplete study"}${preMarketWindowStart && preMarketWindowEnd ? ` · ${timeFmt(preMarketWindowStart)}–${timeFmt(preMarketWindowEnd)} IST` : ""} · latest ${timeFmt(preMarketSnapshotTime)} IST · price gap + order pressure + repeated snapshots`
                : "Waiting for the next 09:00–09:08 IST snapshot · NSE indicative data only, not a BUY/SELL signal"}
            </span>
          </div>
          <div className="watchlistBadge">{preMarketRows.length} candidates</div>
        </div>
        {preMarketRows.length === 0 ? <div className="watchEmpty">No stock meets the movement watch criteria yet. The study needs at least 3 snapshots, a meaningful indicative gap and liquid, consistent order pressure.</div> :
          <div className="tableScroll" style={{maxHeight: 360}}>
            <table style={{minWidth: 1050}}>
              <thead><tr><th>SYMBOL</th><th>DIRECTION</th><th className="right">WATCH SCORE</th><th className="right">CONSISTENCY</th><th className="right">PREV CLOSE</th><th className="right">INDICATIVE GAP</th><th className="right">IEP</th><th className="right">TRADE QTY</th><th className="right">BUY QTY</th><th className="right">SELL QTY</th><th className="right">IMBALANCE</th><th className="right">OI CHANGE %</th><th>FRESH NEWS, IF AVAILABLE</th></tr></thead>
              <tbody>{rankedPreMarketRows.map((row) => (
                <tr key={row.id}>
                  <td className="symbol">{row.symbol}{sectorBadge(row.symbol, row.movement_direction)}{articleBadge(row.symbol, row.snapshot_time)}</td>
                  <td><span className="setupBadge">{row.movement_direction}</span></td>
                  <td className="right num">{row.movement_score}</td>
                  <td className="right num">{row.aligned_snapshots}/3 · {row.observed_snapshots} total</td>
                  <td className="right num">{fmt(row.previous_close)}</td>
                  <td className="right num">{row.indicative_gap_pct == null ? "—" : fmt(row.indicative_gap_pct) + "%"}</td>
                  <td className="right num">{fmt(row.indicative_price)}</td>
                  <td className="right num">{row.indicative_tradable_qty == null ? "—" : Math.round(row.indicative_tradable_qty).toLocaleString("en-IN")}</td>
                  <td className="right num">{row.buy_qty == null ? "—" : Math.round(row.buy_qty).toLocaleString("en-IN")}</td>
                  <td className="right num">{row.sell_qty == null ? "—" : Math.round(row.sell_qty).toLocaleString("en-IN")}</td>
                  <td className="right num">{row.imbalance_qty == null ? "—" : Math.round(row.imbalance_qty).toLocaleString("en-IN")}</td>
                  <td className="right num">{row.oi_change_pct == null ? "—" : fmt(row.oi_change_pct) + "%"}</td>
                  <td>{newsBySymbol.get(row.symbol)?.news_summary ?? "—"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>}
        <div className="watchlistHead">
          <span>Sources: <a href="https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market" target="_blank" rel="noreferrer">NSE Pre-Open Market</a> · <a href="https://www.nseindia.com/market-data/oi-spurts" target="_blank" rel="noreferrer">NSE OI Spurts</a>. Watch score ranks the observed setup; it is not a probability. News appears only when today's timestamp-verified headline is available.</span>
        </div>
      </section>

      <section className="watchlistWrap hotStocksWrap">
        <div className="watchlistHead">
          <div>
            <strong>PRE-MARKET WATCH × ALIGNED CONFIRMED SIGNALS</strong>
            <span>Movement watch candidates whose pre-market direction agrees with a confirmed BUY or SELL signal. This comparison does not create signals.</span>
          </div>
          <div className="watchlistBadge">{preMarketConfirmedRows.length} aligned</div>
        </div>
        {preMarketConfirmedRows.length === 0 ? <div className="watchEmpty">No movement watch candidate has a confirmed signal in the same direction yet.</div> :
          <div className="tableScroll" style={{maxHeight: 320}}>
            <table style={{minWidth: 1050}}>
              <thead><tr><th>SYMBOL</th><th>SIGNAL</th><th className="right">SIGNAL SCORE</th><th>SIGNAL TIME</th><th>PRE-MARKET BIAS</th><th className="right">INDICATIVE GAP</th><th className="right">OI CHANGE</th><th>PRE-MARKET CONTEXT</th></tr></thead>
              <tbody>{preMarketConfirmedRows.map(({signal, premarket}) => (
                <tr key={signal.id}>
                  <td className="symbol">{signal.symbol}{sectorBadge(signal.symbol, signal.signal_type)}{patternBadge(signal)}{articleBadge(signal.symbol, signal.signal_time)}</td>
                  <td><span className="setupBadge">{signal.signal_type}</span></td>
                  <td className="right num">{fmt(signal.score)}</td>
                  <td>{signalClock(signal)}</td>
                  <td><span className="setupBadge">{premarket.preopen_bias || "NEUTRAL / MIXED"}</span></td>
                  <td className="right num">{premarket.indicative_gap_pct == null ? "—" : fmt(premarket.indicative_gap_pct) + "%"}</td>
                  <td className="right num">{premarket.oi_change_pct == null ? "—" : fmt(premarket.oi_change_pct) + "%"}</td>
                  <td>{(premarket.reasons ?? []).join(" · ") || "NSE source match"}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>}
      </section>

      <section className="watchlistWrap hotStocksWrap">
        <div className="watchlistHead">
          <div>
            <strong>COMMON STOCKS · CROSS-SECTION MATCH</strong>
            <span>Confirmed signal + at least one other displayed section. Each distinct heading is counted once; more matches rank first.</span>
          </div>
          <div className="watchlistBadge">{commonStockRows.length} common</div>
        </div>
        {commonStockRows.length === 0 ? <div className="watchEmpty">No confirmed stock appears in another section yet.</div> :
          <div className="tableScroll" style={{maxHeight: 300}}>
            <table style={{minWidth: 850}}>
              <thead><tr><th>SYMBOL</th><th className="right">MATCHING HEADINGS</th><th>SECTIONS</th><th>STATUS</th></tr></thead>
              <tbody>{commonStockRows.map(row => (
                <tr key={row.symbol}>
                  <td className="symbol">{row.symbol}</td>
                  <td className="right num">{row.count}</td>
                  <td style={{whiteSpace:"normal",minWidth:350}}>{row.sections.join(" · ")}</td>
                  <td><span className="setupBadge">CONFIRMED + OTHER SECTION</span></td>
                </tr>
              ))}</tbody>
            </table>
          </div>}
      </section>

      </details>

      <details className="detailGroup signalDetails" open={patternFilter !== "ALL"}><summary>View matching confirmed signals <span>{filtered.length} rows · sortable table</span></summary>
      <section className="tableWrap">
        <div className="tableHead">
          <div><strong>Confirmed Signals</strong><span>{filtered.length} rows · click any column to sort</span></div>
          <div className="legend"><span><i className="legendBuy" /> BUY</span><span><i className="legendSell" /> SELL</span><span>Score / 100</span></div>
        </div>
        <div className="tableScroll">
          <table>
            <thead><tr>{columns.map((col) => (
              <th key={col.key} className={col.align === "right" ? "right" : ""}>
                <button className="sortButton" onClick={() => setSortKey(col.key)}>{col.label}<span>{sortIcon(col.key)}</span></button>
              </th>
            ))}</tr></thead>
            <tbody>
              {loading ? <tr><td colSpan={columns.length} className="empty"><div className="spinner" /><strong>Loading scanner feed…</strong><span>Connecting to live confirmed signals</span></td></tr> :
               filtered.length === 0 ? <tr><td colSpan={columns.length} className="empty"><strong>No signals match the selected filters</strong><span>Choose another pattern or wait for a qualifying completed 3M confirmation.</span></td></tr> :
               filtered.map((signal) => {
                 const isBuy = signal.signal_type.toUpperCase().includes("BUY");
                 const score = Number(signal.score ?? 0);
                 return <tr key={signal.id}>
                   <td className="timeCell">{timeFmt(signal.signal_time)}</td>
                   <td className="symbol">{signal.symbol}{articleBadge(signal.symbol, signal.signal_time)}</td>
                   <td className="patternCell">{patternBadge(signal)}</td>
                   <td className="alignmentCell"><strong>{alignmentFor(signal).count}/4 clues</strong><div>{alignmentFor(signal).labels.map(label => <span key={label}>{label}</span>)}</div>{alignmentFor(signal).unavailable.length > 0 && <small title={alignmentFor(signal).unavailable.join(', ')}>Unavailable: {alignmentFor(signal).unavailable.join(', ')}</small>}</td>
                   <td><span className={isBuy ? "signalBadge buyBadge" : "signalBadge sellBadge"}><b>{isBuy ? "BUY" : "SELL"}</b><em>CONFIRMED</em></span></td>
                   <td className="right"><span className={score >= 80 ? "score high" : score >= 65 ? "score mid" : "score low"}>{score}</span></td>
                   <td className="right num">{fmt(signal.ltp)}</td><td className="right num">{fmt(signal.entry)}</td><td className="right num sl">{fmt(signal.stop_loss)}</td>
                   <td className="right num target">{fmt(signal.target1)}</td><td className="right num target">{fmt(signal.target2)}</td>
                   <td className="right num">{fmt(signal.risk_reward)}</td><td className="right num">{fmt(signal.rvol)}×</td><td className="right num">{fmt(signal.breakout_level)}</td>
                   <td><span className="setupBadge">FIRST BREAK</span></td>
                 </tr>;
               })}
            </tbody>
          </table>
        </div>
      </section>
      </details>

      <footer><span>Prime Scanner · NSE F&O universe · 3-minute engine</span><span>{lastRefresh ? "Updated " + lastRefresh.toLocaleTimeString("en-IN") : "Connecting…"}</span></footer>

      <style jsx>{`
        .patternFilter { display:flex; flex-direction:column; gap:5px; color:#9bb1cd; font-size:10px; font-weight:700; }
        .patternFilter select { background:#0d1d30; color:#d5e8ff; border:1px solid #34506d; border-radius:8px; padding:9px 12px; min-width:215px; font-size:12px; }
        .filterExplanation { max-width:1680px; margin:0 auto 14px; color:#95aec9; font-size:11px; line-height:1.6; }
        .contextGrid { display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:12px; padding:16px; max-height:620px; overflow:auto; }
        .contextCard { padding:15px; background:#0b1626; border:1px solid #29415d; border-radius:12px; margin-bottom:12px; min-width:0; }
        .contextTitle { display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:8px; }
        .contextTitle strong { font-size:15px; color:#e6efff; } .contextTitle span { color:#82d7c0; font-size:11px; }
        .contextCard p { font-size:11px; color:#a6b8d1; line-height:1.6; margin:8px 0; } .contextCard small { font-size:10px; color:#8eabc5; }
        .contextTags { display:flex; gap:6px; flex-wrap:wrap; margin-top:10px; } .contextTags b,.contextTags>span { border:1px solid #2c4763; background:#12263a; padding:5px 7px; border-radius:5px; color:#b9d7ed; font-size:10px; }
        .patternCell { min-width:230px; max-width:320px; white-space:normal; }
        .patternCell :global(small) { display:block; margin:4px 0; font-size:11px; line-height:1.5; }
        :global(.sectorSupport) { display:block; font-size:10px; margin-top:5px; color:#8da0b9; } :global(.sectorSupport.supported) { color:#f5ce79; font-weight:800; padding:4px 7px; border:1px solid #6a562c; border-radius:5px; background:#302719; width:fit-content; }
        .contextNews a { display:block; margin:8px 0; font-size:11px; line-height:1.5; color:#88c9f5; } .contextNews small { display:block; }
        @media(max-width:700px) { .contextGrid {grid-template-columns:1fr;} }
        .openingDesk { max-width:1680px; margin:0 auto 14px; padding:18px; border:1px solid #2b4659; border-radius:16px; background:linear-gradient(135deg,#102c35,#0c1726 48%,#101c2b); }
        .openingHead { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; margin-bottom:15px; }
        .openingHead h2 { margin:5px 0; font-size:21px; letter-spacing:-.5px; }
        .openingHead p { margin:0; color:#9db3c7; font-size:12px; line-height:1.5; }
        .openingCount { flex:none; padding:7px 11px; border:1px solid #397569; border-radius:20px; color:#70dfbd; font-size:11px; font-weight:800; }
        .openingContext { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:13px; }
        .breadthCard,.rotationCard,.openingColumn { background:#0a1623; border:1px solid #274055; border-radius:11px; overflow:hidden; }
        .breadthCard,.rotationCard { padding:12px 14px; }
        .openingContextTitle { display:flex; justify-content:space-between; gap:8px; color:#dce9f4; font-size:11px; font-weight:800; letter-spacing:.5px; }
        .openingContextTitle span { color:#80cbb8; font-size:10px; letter-spacing:0; }
        .breadthNumbers { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:13px 0; }
        .breadthNumbers b { font-size:20px; } .breadthNumbers small { display:block; color:#8fa7b8; font-size:10px; font-weight:600; }
        .openingDesk .up { color:#55d9a6; } .openingDesk .down { color:#ff7e93; }
        .breadthBar { display:flex; justify-content:space-between; height:7px; border-radius:8px; background:#324257; overflow:hidden; }
        .breadthBar i { background:#2dc58f; } .breadthBar em { background:#ed677c; }
        .openingNote { display:block; margin-top:9px; color:#829aaf; font-size:10px; line-height:1.5; }
        .rotationRow { display:flex; justify-content:space-between; gap:12px; padding:5px 0; border-bottom:1px solid #1f3345; color:#bfcfe1; font-size:11px; }
        .rotationRow:first-of-type { margin-top:8px; } .rotationRow b { white-space:nowrap; }
        .openingColumns { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
        .openingColumnTitle { display:flex; justify-content:space-between; padding:11px 13px; font-size:12px; font-weight:900; letter-spacing:.8px; }
        .openingColumnTitle.explosive { background:#124d3d; color:#9bffcf; } .openingColumnTitle.strong { background:#224675; color:#b6d5ff; } .openingColumnTitle.spurt { background:#65431b; color:#ffe1a5; }
        .openingColumnTitle span { opacity:.8; }
        .openingItem { padding:12px 13px; border-top:1px solid #203549; }
        .openingItemTop { display:flex; justify-content:space-between; align-items:center; gap:10px; }
        .openingItemTop strong { font-size:13px; color:#f1f7ff; } .openingItemTop b { font-size:13px; }
        .openingItemTags { display:flex; flex-wrap:wrap; gap:5px; margin-top:7px; }
        .openingItemTags span,.openingSector,.openingConfirmed { display:inline-block; padding:4px 6px; border:1px solid #345167; border-radius:5px; color:#a9c1d5; font-size:10px; }
        .openingItem p { margin:8px 0 0; color:#8fa8bd; font-size:10px; }
        .openingSector { margin:7px 5px 0 0; border-color:#497b60; color:#8fe4ae; }
        .openingConfirmed { margin:7px 0 0; border-color:#496993; color:#a9ccff; }
        .openingFooter { margin-top:13px; }
        .filingsPanel { max-width:1680px; margin:14px auto; padding:18px; border:1px solid #31506a; border-radius:16px; background:linear-gradient(135deg,#10253a,#0b1728 65%); }
        .filingsHead { display:flex; justify-content:space-between; align-items:center; gap:14px; margin-bottom:14px; }
        .filingsHead h2 { margin:4px 0; font-size:19px; }
        .filingsHead p { margin:0; color:#91a9c2; font-size:11px; }
        .filingsCount { padding:7px 11px; border:1px solid #3a607b; border-radius:18px; color:#b5d9ef; font-size:11px; font-weight:800; white-space:nowrap; }
        .filingsGrid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:9px; }
        .filingCard { display:flex; min-width:0; flex-direction:column; padding:12px; border:1px solid #28445d; border-radius:10px; background:#0a1623; color:#dce9f4; }
        .filingCard:hover { border-color:#60caa8; background:#0d1e2d; }
        .filingCardTop { display:flex; justify-content:space-between; align-items:center; gap:6px; margin-bottom:8px; }
        .filingCardTop strong { color:#78e0b4; font-size:13px; }
        .filingCardTop span { color:#f2d38e; font-size:9px; font-weight:800; }
        .filingBadges { display:flex; flex-wrap:wrap; align-items:center; gap:6px; }
        .filingBadges b { color:#a9d8ff; font-size:10px; }
        .filingBadges span { padding:3px 5px; border:1px solid #69562e; border-radius:5px; background:#282214; color:#f1cd79; font-size:8px; font-weight:900; letter-spacing:.35px; }
        .filingCard .filingSummary { min-height:56px; margin:8px 0 5px; color:#c0cedd; font-size:11px; line-height:1.5; }
        .filingDetails { margin:3px 0 9px; color:#8197ad; font-size:9px; }
        .filingDetails summary { cursor:pointer; }
        .filingDetails p { margin:5px 0; color:#91a9c2; font-size:10px; line-height:1.5; }
        .filingCardFooter { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-top:auto; }
        .filingCard small { color:#718ba6; font-size:9px; }
        .filingCardFooter a { color:#70dcb1; font-size:9px; font-weight:800; text-decoration:none; }
        .filingCardFooter a:hover { text-decoration:underline; }
        .filingsEmpty { padding:18px; border:1px dashed #304963; border-radius:10px; color:#91a9c2; font-size:12px; }
        .filingTag { display:inline-flex; align-items:center; margin:5px 5px 0 0; padding:4px 7px; border:1px solid #7b6631; border-radius:6px; background:#3d3217; color:#ffdb78 !important; font-size:9px !important; font-weight:900 !important; letter-spacing:.35px; line-height:1.25; text-decoration:none; white-space:nowrap; }
        .filingTag:hover { border-color:#ffd36b; background:#59471b; color:#fff0bf !important; }
        .desk,.evidence,.detailGroup { max-width:1680px; margin:0 auto 14px; border:1px solid #24364d; border-radius:16px; background:#0c1624; overflow:hidden; }
        .desk { padding:18px; background:linear-gradient(140deg,#10213a,#0b1523 50%,#10192a); }
        .deskHead { display:flex; justify-content:space-between; gap:18px; align-items:flex-start; margin-bottom:16px; }
        .deskKicker { color:#5dd4b0; font-size:10px; font-weight:800; letter-spacing:1.5px; }
        .desk h2,.evidence h2 { margin:5px 0; font-size:21px; letter-spacing:-.5px; }
        .desk p,.evidence p { margin:0; color:#9baec8; font-size:12px; line-height:1.5; }
        .statusChip { border:1px solid #765c2e; background:#302719; color:#f0bd65; border-radius:9px; padding:10px 12px; font-size:11px; font-weight:800; white-space:nowrap; }
        .statusChip.live { border-color:#22644d; background:#0e2b23; color:#5de1aa; }
        .statusChip small { display:block; margin-top:3px; color:#a8b7ca; font-size:10px; font-weight:500; }
        .deskGrid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
        .deskPanel { border:1px solid #253952; border-radius:11px; background:#0a1320; overflow:hidden; }
        .deskPanelTitle { display:flex; justify-content:space-between; padding:11px 13px; background:#142238; color:#dce8f7; font-size:11px; font-weight:800; letter-spacing:.5px; }
        .deskPanelTitle span { color:#91a6c1; font-weight:600; letter-spacing:0; }
        .deskItem { display:flex; align-items:center; justify-content:space-between; gap:10px; padding:10px 13px; border-top:1px solid #1b2c42; }
        .deskItem b { color:#f0f5fb; font-size:13px; } .deskItem small { display:block; margin-top:3px; color:#97a9be; font-size:11px; } .deskItem strong { color:#d9e9fb; font-size:13px; }
        .deskItem em { font-size:10px; font-style:normal; margin-left:5px; } .deskItem em.up { color:#54dbaa; } .deskItem em.down { color:#ff8292; }
        .deskFoot { padding:10px 13px; color:#8396af; font-size:10px; border-top:1px solid #1b2c42; }
        .deskEmpty { padding:18px 13px; color:#93a5bc; font-size:12px; }
        .evidence { display:flex; align-items:center; flex-wrap:wrap; justify-content:space-between; gap:14px; padding:17px 18px; }
        .evidenceStats { display:grid; grid-template-columns:repeat(4,minmax(105px,1fr)); gap:8px; }
        .evidenceStats div { padding:9px 10px; border:1px solid #263b54; border-radius:9px; background:#111e30; }
        .evidenceStats b { display:block; color:#e9f3ff; font-size:17px; } .evidenceStats span { display:block; color:#95a9c2; font-size:10px; }
        .scoreBands { display:flex; flex-wrap:wrap; gap:8px; flex-basis:100%; align-items:center; color:#9aafc8; font-size:10px; } .scoreBands b { color:#dce9f8; } .scoreBands span { border:1px solid #2a4059; border-radius:6px; padding:5px 7px; }
        .evidenceNote { flex-basis:100%; color:#8ea0b7; font-size:10px; }
        .detailGroup { border-color:#263952; } .detailGroup summary { display:flex; align-items:center; justify-content:space-between; gap:12px; cursor:pointer; padding:15px 18px; color:#e7f1fc; font-size:13px; font-weight:800; list-style:none; }
        .detailGroup summary::-webkit-details-marker { display:none; } .detailGroup summary::after { content:"＋"; color:#83a5cf; } .detailGroup[open] summary::after { content:"−"; }
        .detailGroup summary span { margin-left:auto; color:#8ba0b9; font-size:10px; font-weight:500; }
        .detailGroup .watchlistWrap,.detailGroup .tableWrap { margin:10px; max-width:none; }
        * { box-sizing: border-box; }
        .page { min-height:100vh; padding:26px 28px 18px; background:radial-gradient(circle at 50% -20%,#12203a 0,#080d16 38%,#060a11 100%); color:#e8edf5; font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
        .header,.cards,.toolbar,.tableWrap,footer,.error { max-width:1680px; margin-left:auto; margin-right:auto; }
        .header { display:flex; align-items:center; justify-content:space-between; gap:24px; margin-bottom:22px; }
        .brandRow { display:flex; align-items:center; gap:12px; }
        .logoMark { width:38px; height:38px; border-radius:10px; display:grid; place-items:center; background:linear-gradient(135deg,#1d7cff,#35d49a); color:white; font-weight:900; box-shadow:0 8px 24px rgba(29,124,255,.25); }
        .eyebrow { color:#7e8da5; font-size:10px; letter-spacing:2.2px; font-weight:800; }
        h1 { margin:2px 0 2px; font-size:30px; letter-spacing:-1.1px; line-height:1.1; }
        p { margin:9px 0 0 50px; color:#7e8da5; font-size:12px; }
        .headerRight { display:flex; align-items:center; gap:12px; }
        .marketBadge,.modePill { display:flex; align-items:center; gap:7px; border:1px solid #223149; background:rgba(13,21,34,.82); border-radius:999px; padding:9px 12px; color:#aebbd0; font-size:10px; font-weight:800; letter-spacing:.5px; }
        .pulse,.greenDot { width:7px; height:7px; border-radius:50%; background:#28d486; box-shadow:0 0 12px rgba(40,212,134,.8); }
        .refreshText { color:#64748a; font-size:11px; } .refreshText b { color:#a9b6c9; }
        .cards { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:18px; }
        .card { position:relative; overflow:hidden; background:linear-gradient(180deg,rgba(16,26,42,.96),rgba(10,17,28,.96)); border:1px solid #1d2a3d; border-radius:14px; padding:15px 17px; box-shadow:0 12px 30px rgba(0,0,0,.16); }
        .card:after { content:""; position:absolute; right:-25px; bottom:-45px; width:100px; height:100px; border-radius:50%; background:rgba(72,113,180,.07); }
        .cardTop { display:flex; justify-content:space-between; align-items:center; color:#72829a; font-size:10px; font-weight:800; letter-spacing:.8px; }
        .miniIcon { color:#52647e; font-size:14px; } .card strong { display:block; margin-top:8px; font-size:29px; letter-spacing:-1px; } .card small { display:block; margin-top:3px; color:#64748a; font-size:10px; }
        .card.buy strong,.buyText { color:#31d58a; } .card.sell strong,.sellText { color:#ff6680; }
        .toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }
        .toolbarLeft { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
        .tabs { display:flex; gap:5px; padding:4px; border:1px solid #1b283a; background:#0a111c; border-radius:10px; }
        .tab { border:0; background:transparent; color:#738299; padding:8px 12px; border-radius:7px; cursor:pointer; font-size:10px; font-weight:800; letter-spacing:.3px; }
        .tab:hover { color:#cbd5e4; } .tab.active { background:#1a2941; color:#f5f8fc; box-shadow:inset 0 0 0 1px #304665; }
        .modePill { padding:8px 11px; font-size:9px; }
        .searchBox { display:flex; align-items:center; gap:8px; width:280px; border:1px solid #223149; background:#0b1320; border-radius:9px; padding:0 11px; color:#63738b; }
        .searchBox span { font-size:18px; } .searchBox input { width:100%; border:0; outline:0; background:transparent; color:#dbe3ef; padding:9px 0; font-size:11px; } .searchBox input::placeholder { color:#53627a; }
        .error { margin-bottom:12px; padding:11px 14px; background:#2a151d; color:#ff9bac; border:1px solid #592733; border-radius:9px; font-size:12px; }
        .selectorWrap { max-width:1680px; margin:0 auto 12px; overflow:hidden; border:1px solid #1c293b; border-radius:14px; background:rgba(10,17,28,.96); box-shadow:0 12px 32px rgba(0,0,0,.16); }
        .selectorHead { display:flex; align-items:center; justify-content:space-between; gap:15px; padding:13px 16px; border-bottom:1px solid #1b2739; background:linear-gradient(180deg,#101a2a,#0c1421); }
        .selectorHead strong { display:block; color:#e7edf6; font-size:12px; letter-spacing:.8px; }
        .selectorHead span { display:block; margin-top:3px; color:#65758d; font-size:9px; }
        .selectorNote { color:#71829a; font-size:9px; white-space:nowrap; }
        .selectorGrid { display:grid; grid-template-columns:1fr 1fr; gap:1px; background:#1b2739; }
        .selectorPanel { background:#0b131f; min-width:0; }
        .selectorPanelTitle { display:flex; justify-content:space-between; align-items:center; padding:9px 13px; color:#71829a; font-size:9px; font-weight:800; letter-spacing:.7px; }
        .selectorPanelTitle b { color:#9eabc0; font-size:9px; }
        .selectorRow { display:grid; grid-template-columns:28px minmax(105px,160px) 1fr 75px; gap:9px; align-items:center; padding:9px 12px; border-top:1px solid #162233; }
        .selectorRank { width:23px; height:23px; display:grid; place-items:center; border-radius:6px; background:#141f2e; color:#9eabc0; font-size:9px; font-weight:900; }
        .selectorSymbol strong { display:block; color:#edf2f8; font-size:10px; }
        .selectorSymbol small { display:block; margin-top:2px; color:#61728a; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:8px; }
        .selectorReasons { display:flex; flex-wrap:wrap; gap:4px; }
        .selectorReasons span { padding:3px 5px; border:1px solid #25354b; border-radius:4px; background:#111b29; color:#8394ab; font-size:8px; white-space:nowrap; }
        .selectorReasons .alignmentChip { color:#61e5b3; border-color:#1e6048; background:#0d291f; }
        .alignmentCell { min-width:210px; max-width:300px; }
        .alignmentCell strong { color:#61e5b3; font-size:11px; }
        .alignmentCell div { display:flex; flex-wrap:wrap; gap:3px; margin-top:4px; }
        .alignmentCell div span { color:#b2d8c9; border:1px solid #244e42; border-radius:4px; padding:2px 4px; font-size:9px; }
        .alignmentCell small { display:block; color:#71829a; font-size:8px; margin-top:4px; }
        .selectorScore { display:grid; place-items:center; min-width:35px; padding:5px 4px; border-radius:6px; font-size:11px; font-weight:900; }
        .buyScore { color:#3cdda0; background:#0d291f; border:1px solid #1e6048; }
        .sellScore { color:#ff7189; background:#2a151c; border:1px solid #63303d; }
        .selectorEmpty { padding:17px 13px; color:#596a82; font-size:9px; }
        .watchlistWrap { max-width:1680px; margin:0 auto 12px; overflow:hidden; border:1px solid #1c293b; border-radius:14px; background:rgba(10,17,28,.96); box-shadow:0 12px 32px rgba(0,0,0,.16); }
        .watchlistHead { display:flex; align-items:center; justify-content:space-between; gap:15px; padding:13px 16px; border-bottom:1px solid #1b2739; background:linear-gradient(180deg,#101a2a,#0c1421); }
        .watchlistHead strong { display:block; color:#e7edf6; font-size:12px; letter-spacing:.8px; }
        .watchlistHead span { display:block; margin-top:3px; color:#65758d; font-size:9px; }
        .watchlistBadge { color:#aebbd0; background:#111d2d; border:1px solid #263850; border-radius:999px; padding:5px 9px; font-size:9px; font-weight:800; }
        .watchSingle { background:#0b131f; }
        .hotSingle { background:#0b131f; }
        .hotRow { display:grid; grid-template-columns:28px minmax(110px,170px) minmax(300px,1.1fr) minmax(300px,1.6fr) 42px; gap:9px; align-items:center; padding:10px 12px; border-top:1px solid #162233; }
        .hotMetrics { display:flex; flex-wrap:wrap; gap:4px; }
        .hotMetrics span { padding:3px 5px; border:1px solid #25354b; border-radius:4px; background:#111b29; color:#8394ab; font-size:8px; white-space:nowrap; }
        .hotNews { min-width:0; overflow:hidden; color:#7e8fa7; font-size:8px; }
        .hotNews span,.hotNews small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .hotNews small { margin-top:4px; color:#52647d; font-size:7px; }
        .watchDirection { font-size:9px; font-weight:900; letter-spacing:.5px; }
        .watchPanel { background:#0b131f; min-width:0; }
        .watchPanelTitle { display:flex; justify-content:space-between; padding:9px 13px; color:#71829a; font-size:9px; font-weight:800; letter-spacing:.7px; }
        .watchPanelTitle b { color:#9eabc0; }
        .watchRow { display:grid; grid-template-columns:28px minmax(110px,170px) 55px 1fr 42px; gap:9px; align-items:center; padding:9px 12px; border-top:1px solid #162233; }
        .watchRank { width:23px; height:23px; display:grid; place-items:center; border-radius:6px; background:#141f2e; color:#9eabc0; font-size:9px; font-weight:900; }
        .watchSymbol strong { display:block; color:#edf2f8; font-size:10px; }
        .watchSymbol small { display:block; margin-top:2px; color:#61728a; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:8px; }
        .watchReasons { display:flex; flex-wrap:wrap; gap:4px; }
        .watchReasons span { padding:3px 5px; border:1px solid #25354b; border-radius:4px; background:#111b29; color:#8394ab; font-size:8px; white-space:nowrap; }
        .watchScore { display:grid; place-items:center; min-width:35px; padding:5px 4px; border-radius:6px; color:#d8e2ef; background:#151f2e; border:1px solid #2a3a51; font-size:11px; font-weight:900; }
        .watchPanel.buyPanel .watchScore { color:#3cdda0; background:#0d291f; border-color:#1e6048; }
        .watchPanel.sellPanel .watchScore { color:#ff7189; background:#2a151c; border-color:#63303d; }
        .watchEmpty { padding:17px 13px; color:#596a82; font-size:9px; }
        .tableWrap { overflow:hidden; background:rgba(10,17,28,.96); border:1px solid #1c293b; border-radius:14px; box-shadow:0 16px 45px rgba(0,0,0,.2); }
        .tableHead { display:flex; align-items:center; justify-content:space-between; padding:14px 16px; border-bottom:1px solid #1b2739; background:linear-gradient(180deg,#101a2a,#0c1421); }
        .tableHead strong { display:block; font-size:13px; color:#e5ebf4; } .tableHead span { color:#66768e; font-size:10px; margin-left:9px; }
        .legend { display:flex; gap:14px; color:#687890; font-size:10px; } .legend i { display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:5px; } .legendBuy { background:#31d58a; } .legendSell { background:#ff6680; }
        .tableScroll { overflow:auto; max-height:calc(100vh - 330px); scrollbar-width:thin; scrollbar-color:#26364e #0a111b; }
        table { width:100%; border-collapse:separate; border-spacing:0; min-width:1200px; }
        th { position:sticky; top:0; z-index:2; background:#0d1725; border-bottom:1px solid #26354b; color:#6f8098; font-size:9px; text-align:left; letter-spacing:.65px; padding:10px 11px; white-space:nowrap; }
        th.right,.right { text-align:right; }
        .sortButton { width:100%; border:0; background:transparent; color:inherit; cursor:pointer; display:flex; align-items:center; gap:7px; justify-content:flex-start; font:inherit; letter-spacing:inherit; padding:0; text-align:inherit; }
        th.right .sortButton { justify-content:flex-end; } .sortButton:hover { color:#dbe5f3; } .sortButton span { color:#3f536e; font-size:11px; } th:hover .sortButton span { color:#8ca0ba; }
        tbody tr { transition:background .12s ease; } tbody tr:nth-child(even) { background:rgba(255,255,255,.012); } tbody tr:hover { background:rgba(50,105,170,.09); }
        td { padding:11px; border-bottom:1px solid #141f2e; color:#aebacd; font-size:11px; white-space:nowrap; vertical-align:middle; }
        tbody tr:last-child td { border-bottom:0; }
        .timeCell { color:#7f90a8; font-variant-numeric:tabular-nums; } .symbol { color:#f1f5fa; font-weight:800; } .symbol small { display:block; max-width:175px; overflow:hidden; text-overflow:ellipsis; margin-top:3px; color:#687990; font-size:9px; font-weight:500; }
        .signalBadge { display:inline-flex; flex-direction:column; align-items:center; min-width:67px; padding:4px 8px; border-radius:6px; line-height:1.05; border:1px solid; } .signalBadge b { font-size:10px; letter-spacing:.6px; } .signalBadge em { margin-top:2px; font-size:7px; font-style:normal; opacity:.65; }
        .buyBadge { color:#34db91; border-color:#1e6648; background:#0d251c; } .sellBadge { color:#ff7087; border-color:#68303e; background:#2a141b; }
        .tfBadge { display:inline-block; min-width:29px; text-align:center; padding:4px 6px; border-radius:5px; background:#151f30; border:1px solid #26364e; color:#aebbd0; font-size:9px; font-weight:800; }
        .score { display:inline-grid; place-items:center; min-width:35px; padding:4px 7px; border-radius:5px; font-weight:900; font-variant-numeric:tabular-nums; } .score.high { color:#42dda0; background:#0c2a20; border:1px solid #1a5b43; } .score.mid { color:#ffd27a; background:#2b2515; border:1px solid #62522b; } .score.low { color:#ff889c; background:#2a171e; border:1px solid #5a2936; }
        .grade { color:#bac6d8; font-size:10px; font-weight:700; } .sectorCell small { display:block; margin-top:3px; color:#64758d; font-size:9px; } .rankBadge { display:inline-block; padding:4px 6px; border-radius:5px; background:#151f2e; color:#91a1b8; font-size:9px; font-weight:800; } .rankBadge.top { color:#f0c56d; background:#2a2415; border:1px solid #5c4c27; }
        .num { font-variant-numeric:tabular-nums; color:#bdc8d8; } .sl { color:#ff8799; } .target { color:#65dba5; }
        .setupBadge { color:#8fa3be; background:#111b2a; border:1px solid #25354b; padding:4px 7px; border-radius:5px; font-size:8px; font-weight:800; letter-spacing:.4px; }
        .empty { height:220px; text-align:center; vertical-align:middle; color:#6c7c93; } .empty strong,.empty span { display:block; } .empty strong { color:#aebbd0; margin-bottom:6px; font-size:13px; } .empty span { font-size:10px; }
        .spinner { width:22px; height:22px; border:2px solid #26364d; border-top-color:#4d9cff; border-radius:50%; margin:0 auto 12px; animation:spin .8s linear infinite; } @keyframes spin { to { transform:rotate(360deg); } }
        footer { display:flex; justify-content:space-between; margin-top:10px; padding:0 2px; color:#53647b; font-size:9px; }
        @media (max-width:900px) { .page { padding:16px; } .header,.toolbar,.deskHead,.openingHead { align-items:flex-start; flex-direction:column; } .headerRight { width:100%; justify-content:space-between; } .cards { grid-template-columns:repeat(2,1fr); } .searchBox { width:100%; } .selectorGrid,.deskGrid,.openingContext { grid-template-columns:1fr; } .openingColumns { grid-template-columns:1fr; } .filingsGrid { grid-template-columns:repeat(2,minmax(0,1fr)); } .filingsHead { align-items:flex-start; } .selectorHead { align-items:flex-start; flex-direction:column; } .selectorNote { white-space:normal; } .tableScroll { max-height:calc(100vh - 430px); } .evidenceStats { width:100%; grid-template-columns:repeat(2,1fr); } .detailGroup summary span { display:none; } }
      `}</style>
    </main>
  );
}

