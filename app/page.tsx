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
  metadata?: { timeframe?: string };
};

const fmt = (value: number | null, digits = 2) =>
  value === null || value === undefined || Number.isNaN(Number(value)) ? "—" : Number(value).toFixed(digits);

const timeFmt = (value: string | null) =>
  value ? new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value)) : "—";

export default function Home() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [filter, setFilter] = useState<"ALL" | "BUY" | "SELL">("ALL");
  const [timeframe, setTimeframe] = useState("ALL");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  async function loadSignals() {
    try {
      const response = await fetch("/api/signals?limit=200", { cache: "no-store" });
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

  const filtered = useMemo(() => signals.filter((signal) => {
    const sideOk = filter === "ALL" || signal.signal_type.toUpperCase().includes(filter);
    const tf = String(signal.metadata?.timeframe ?? "").toUpperCase();
    const tfOk = timeframe === "ALL" || tf.includes(timeframe);
    return sideOk && tfOk;
  }), [signals, filter, timeframe]);

  const buys = signals.filter((s) => s.signal_type.toUpperCase().includes("BUY")).length;
  const sells = signals.filter((s) => s.signal_type.toUpperCase().includes("SELL")).length;
  const active = signals.filter((s) => s.is_active !== false).length;

  return (
    <main className="page">
      <header className="header">
        <div><div className="eyebrow">PRIME TECHNICAL</div><h1>Live Scanner</h1><p>Confirmed intraday signals from the Supabase signal feed.</p></div>
        <div className="live-pill"><span className="dot" /> LIVE · 5s</div>
      </header>

      <section className="cards">
        <div className="card"><span>Total Signals</span><strong>{signals.length}</strong></div>
        <div className="card buy"><span>BUY CONFIRMED</span><strong>{buys}</strong></div>
        <div className="card sell"><span>SELL CONFIRMED</span><strong>{sells}</strong></div>
        <div className="card"><span>Active</span><strong>{active}</strong></div>
      </section>

      <section className="toolbar">
        <div className="tabs">{(["ALL", "BUY", "SELL"] as const).map((item) => (
          <button key={item} className={filter === item ? "tab active" : "tab"} onClick={() => setFilter(item)}>
            {item === "ALL" ? "ALL TODAY" : item + " CONFIRMED"}
          </button>
        ))}</div>
        <div className="tabs">{["ALL", "1M", "3M", "5M"].map((item) => (
          <button key={item} className={timeframe === item ? "tab active" : "tab"} onClick={() => setTimeframe(item)}>{item}</button>
        ))}</div>
      </section>

      {error && <div className="error">{error}</div>}

      <section className="tableWrap">
        <table>
          <thead><tr>
            {["TIME","SYMBOL","SIGNAL","TF","SCORE","GRADE","LTP","ENTRY","SL","T1","T2","R:R","RVOL","BREAKOUT","SETUP"].map((h) => <th key={h}>{h}</th>)}
          </tr></thead>
          <tbody>
            {loading ? <tr><td colSpan={15} className="empty">Loading signal feed…</td></tr> :
             filtered.length === 0 ? <tr><td colSpan={15} className="empty"><strong>No signals yet</strong><span>When the scanner writes confirmed signals to scanner_signals, they will appear here automatically.</span></td></tr> :
             filtered.map((signal) => {
               const side = signal.signal_type.toUpperCase().includes("BUY") ? "buyText" : "sellText";
               const tf = String(signal.metadata?.timeframe ?? "—").toUpperCase();
               return <tr key={signal.id}>
                 <td>{timeFmt(signal.signal_time)}</td><td className="symbol">{signal.symbol}</td>
                 <td className={side}>{signal.signal_type}</td><td>{tf}</td><td>{signal.score ?? "—"}</td><td>{signal.grade ?? "—"}</td>
                 <td>{fmt(signal.ltp)}</td><td>{fmt(signal.entry)}</td><td>{fmt(signal.stop_loss)}</td><td>{fmt(signal.target1)}</td>
                 <td>{fmt(signal.target2)}</td><td>{fmt(signal.risk_reward)}</td><td>{fmt(signal.rvol)}</td><td>{fmt(signal.breakout_level)}</td><td>{signal.setup ?? "—"}</td>
               </tr>;
             })}
          </tbody>
        </table>
      </section>

      <footer>{lastRefresh ? "Last refresh: " + lastRefresh.toLocaleTimeString("en-IN") : "Connecting…"}</footer>

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
        .symbol { color:#fff; font-weight:700; } .empty { height:190px; text-align:center; vertical-align:middle; color:#758399; } .empty strong,.empty span { display:block; } .empty strong { color:#aeb9c9; margin-bottom:7px; font-size:14px; }
        footer { max-width:1600px; margin:12px auto 0; color:#657389; font-size:11px; }
        @media (max-width:800px) { .page { padding:16px; } .cards { grid-template-columns:repeat(2,1fr); } .header { flex-direction:column; } }
      `}</style>
    </main>
  );
}
