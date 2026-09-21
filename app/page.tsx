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
        .tableWrap { overflow:hidden; background:rgba(10,17,28,.96); border:1px solid #1c293b; border-radius:14px; box-shadow:0 16px 45px rgba(0,0,0,.2); }
        .tableHead { display:flex; align-items:center; justify-content:space-between; padding:14px 16px; border-bottom:1px solid #1b2739; background:linear-gradient(180deg,#101a2a,#0c1421); }
        .tableHead strong { display:block; font-size:13px; color:#e5ebf4; } .tableHead span { color:#66768e; font-size:10px; margin-left:9px; }
        .legend { display:flex; gap:14px; color:#687890; font-size:10px; } .legend i { display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:5px; } .legendBuy { background:#31d58a; } .legendSell { background:#ff6680; }
        .tableScroll { overflow:auto; max-height:calc(100vh - 330px); scrollbar-width:thin; scrollbar-color:#26364e #0a111b; }
        table { width:100%; border-collapse:separate; border-spacing:0; min-width:1450px; }
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
        @media (max-width:900px) { .page { padding:16px; } .header,.toolbar { align-items:flex-start; flex-direction:column; } .headerRight { width:100%; justify-content:space-between; } .cards { grid-template-columns:repeat(2,1fr); } .searchBox { width:100%; } .tableScroll { max-height:calc(100vh - 430px); } }
      `}</style>
    </main>
  );
}

