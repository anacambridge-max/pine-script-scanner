'use client'

import { useEffect, useMemo, useState } from "react";

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
  metadata?: { timeframe?: string; company_name?: string; sector?: string; sector_change_percent?: number; sector_rank?: number; sector_rank_type?: string; score_breakdown?: Record<string, unknown> };
};

const fmt = (value: number | null, digits = 2) =>
  value === null || value === undefined || Number.isNaN(Number(value)) ? "—" : Number(value).toFixed(digits);

const timeFmt = (value: string | null) =>
  value ? new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value)) : "—";

export default function Home() {
  type SortKey = "signal_time" | "symbol" | "signal_type" | "timeframe" | "score" | "grade" | "sector" | "sector_rank" | "ltp" | "entry" | "stop_loss" | "target1" | "target2" | "risk_reward" | "rvol" | "breakout_level" | "setup";
  const [signals, setSignals] = useState<Signal[]>([]);
  const [filter, setFilter] = useState<"ALL" | "BUY" | "SELL">("ALL");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [sort, setSort] = useState<{key: SortKey; dir: "asc" | "desc"}>({ key: "signal_time", dir: "desc" });

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
    const timer = window.setInterval(loadSignals, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toUpperCase();
    const rows = signals.filter((signal) => {
      const sideOk = filter === "ALL" || signal.signal_type.toUpperCase().includes(filter);
      const haystack = [signal.symbol, signal.metadata?.company_name, signal.metadata?.sector, signal.setup].filter(Boolean).join(" ").toUpperCase();
      return sideOk && (!q || haystack.includes(q));
    });

    return rows.sort((x, y) => {
      const value = (s: Signal): string | number => {
        switch (sort.key) {
          case "signal_time": return s.signal_time ? new Date(s.signal_time).getTime() : 0;
          case "symbol": return s.symbol;
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
  }, [signals, filter, search, sort]);

  const setSortKey = (key: SortKey) => {
    setSort((current) => current.key === key
      ? { key, dir: current.dir === "asc" ? "desc" : "asc" }
      : { key, dir: key === "signal_time" ? "desc" : "desc" });
  };

  const buys = signals.filter((s) => s.signal_type.toUpperCase().includes("BUY")).length;
  const sells = signals.filter((s) => s.signal_type.toUpperCase().includes("SELL")).length;
  const avgScore = signals.length ? Math.round(signals.reduce((sum, s) => sum + Number(s.score || 0), 0) / signals.length) : 0;
  const topSector = [...signals].filter(s => s.metadata?.sector).sort((a,b) => Number(b.score||0)-Number(a.score||0))[0]?.metadata?.sector;

  const columns: { key: SortKey; label: string; align?: "right" }[] = [
    { key: "signal_time", label: "TIME" },
    { key: "symbol", label: "SYMBOL / COMPANY" },
    { key: "signal_type", label: "SIGNAL" },
    { key: "timeframe", label: "TF" },
    { key: "score", label: "SCORE", align: "right" },
    { key: "grade", label: "GRADE" },
    { key: "sector", label: "SECTOR" },
    { key: "sector_rank", label: "SECTOR RANK", align: "right" },
    { key: "ltp", label: "LTP", align: "right" },
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
        <div className="headerRight"><div className="marketBadge"><span className="pulse" /> MARKET FEED</div><div className="refreshText">Auto refresh <b>5s</b></div></div>
      </header>

      <section className="cards">
        <div className="card"><div className="cardTop"><span>CONFIRMED TODAY</span><span className="miniIcon">◷</span></div><strong>{signals.length}</strong><small>3-minute signals</small></div>
        <div className="card buy"><div className="cardTop"><span>BUY CONFIRMED</span><span className="miniIcon">↗</span></div><strong>{buys}</strong><small>PDH close-break</small></div>
        <div className="card sell"><div className="cardTop"><span>SELL CONFIRMED</span><span className="miniIcon">↘</span></div><strong>{sells}</strong><small>PDL close-break</small></div>
        <div className="card"><div className="cardTop"><span>AVG SCORE</span><span className="miniIcon">★</span></div><strong>{avgScore}</strong><small>{topSector ? `Top signal sector: ${topSector}` : "Waiting for sector data"}</small></div>
      </section>

      <section className="toolbar">
        <div className="toolbarLeft">
          <div className="tabs">{(["ALL", "BUY", "SELL"] as const).map((item) => (
            <button key={item} className={filter === item ? "tab active" : "tab"} onClick={() => setFilter(item)}>
              {item === "ALL" ? "ALL TODAY" : item === "BUY" ? "BUY CONFIRMED" : "SELL CONFIRMED"}
            </button>
          ))}</div>
          <div className="modePill"><span className="greenDot" /> F&O · 3M · FIRST BREAK · 2× VOL</div>
        </div>
        <label className="searchBox"><span>⌕</span><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search symbol, company or sector…" /></label>
      </section>

      {error && <div className="error">{error}</div>}

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
              {loading ? <tr><td colSpan={17} className="empty"><div className="spinner" /><strong>Loading scanner feed…</strong><span>Connecting to live confirmed signals</span></td></tr> :
               filtered.length === 0 ? <tr><td colSpan={17} className="empty"><strong>No confirmed signals</strong><span>The scanner will add a row when a 3M candle closes through the first PDH/PDL break with 2× SMA20 volume.</span></td></tr> :
               filtered.map((signal) => {
                 const isBuy = signal.signal_type.toUpperCase().includes("BUY");
                 const tf = String(signal.metadata?.timeframe ?? "3").toUpperCase();
                 const rank = signal.metadata?.sector_rank;
                 const rankType = signal.metadata?.sector_rank_type;
                 const score = Number(signal.score ?? 0);
                 return <tr key={signal.id}>
                   <td className="timeCell">{timeFmt(signal.signal_time)}</td>
                   <td className="symbol"><div>{signal.symbol}</div><small>{signal.metadata?.company_name ?? signal.symbol}</small></td>
                   <td><span className={isBuy ? "signalBadge buyBadge" : "signalBadge sellBadge"}><b>{isBuy ? "BUY" : "SELL"}</b><em>CONFIRMED</em></span></td>
                   <td><span className="tfBadge">{tf}M</span></td>
                   <td className="right"><span className={score >= 80 ? "score high" : score >= 65 ? "score mid" : "score low"}>{score}</span></td>
                   <td><span className="grade">{signal.grade ?? "—"}</span></td>
                   <td><div className="sectorCell">{signal.metadata?.sector ?? "—"}{signal.metadata?.sector_change_percent != null && <small>{Number(signal.metadata.sector_change_percent).toFixed(2)}%</small>}</div></td>
                   <td className="right">{rank ? <span className={rank <= 3 ? "rankBadge top" : "rankBadge"}>#{rank}{rankType ? ` · ${rankType.replace("TOP 3 ", "")}` : ""}</span> : "—"}</td>
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

      <footer><span>Prime Scanner · NSE F&O universe · 3-minute engine</span><span>{lastRefresh ? "Updated " + lastRefresh.toLocaleTimeString("en-IN") : "Connecting…"}</span></footer>

      <style jsx>{`
        * { box-sizing: border-box; }
        .page { min-height: 100vh; padding: 28px; background: #070b12; color: #e8edf5; font-family: Arial, sans-serif; }
        .header { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; max-width:1600px; margin:0 auto 24px; }
        .eyebrow { color:#7f8da3; font-size:11px; letter-spacing:2px; font-weight:700; }
        h1 { margin:5px 0 4px; font-size:34px; letter-spacing:-1px; } p { margin:0; color:#8794a8; }
        .live-pill { border:1px solid #263449; background:#0c1320; border-radius:999px; padding:10px 14px; font-size:12px; font-weight:700; color:#b9c6d8; }
        .dot { display:inline-block; width:7px; height:7px; background:#26d47b; border-radius:50%; margin-right:7px; box-shadow:0 0 10px #26d47b; }
        .cards { max-width:1600px; margin:0 auto 18px; display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
        .card { background:#0c1320; border:1px solid #1d293a; border-radius:12px; padding:16px 18px; }
        .card span { display:block; color:#7f8da3; font-size:11px; font-weight:700; letter-spacing:.6px; } .card strong { display:block; margin-top:7px; font-size:28px; }
        .card.buy strong,.buyText { color:#2bd681; } .card.sell strong,.sellText { color:#ff637d; }
        .toolbar { max-width:1600px; margin:0 auto 14px; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }
        .tabs { display:flex; gap:7px; flex-wrap:wrap; } .tab { border:1px solid #263449; background:#0c1320; color:#92a0b5; padding:9px 12px; border-radius:8px; cursor:pointer; font-size:11px; font-weight:700; }
        .tab.active { background:#18243a; color:#f1f5fa; border-color:#3a4e6b; } .error { max-width:1600px; margin:0 auto 14px; padding:12px 14px; background:#29141b; color:#ff9bad; border:1px solid #5a2531; border-radius:9px; }
        .tableWrap { max-width:1600px; margin:0 auto; overflow-x:auto; background:#0c1320; border:1px solid #1d293a; border-radius:12px; }
        table { width:100%; border-collapse:collapse; min-width:1250px; } th { color:#6f7d92; font-size:10px; text-align:left; letter-spacing:.6px; padding:12px 10px; border-bottom:1px solid #1d293a; white-space:nowrap; }
        td { padding:12px 10px; border-bottom:1px solid #141e2c; font-size:12px; white-space:nowrap; color:#b8c3d3; } tr:last-child td { border-bottom:0; }
         .symbol { color:#fff; font-weight:700; } .company { display:block; margin-top:4px; color:#718097; font-size:10px; font-weight:500; max-width:190px; overflow:hidden; text-overflow:ellipsis; } .empty { height:190px; text-align:center; vertical-align:middle; color:#758399; } .empty strong,.empty span { display:block; } .empty strong { color:#aeb9c9; margin-bottom:7px; font-size:14px; }
        footer { max-width:1600px; margin:12px auto 0; color:#657389; font-size:11px; }
        @media (max-width:800px) { .page { padding:16px; } .cards { grid-template-columns:repeat(2,1fr); } .header { flex-direction:column; } }
      `}</style>
    </main>
  );
}

