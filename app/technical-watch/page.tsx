'use client';

import { useEffect, useState } from 'react';

type Row = {
  id: string; symbol: string; company_name?: string; trade_date: string;
  technical_score: number; score: number; change_percent?: number | null;
  volume_multiple?: number | null; reasons?: string[];
};

export default function TechnicalWatchPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [day, setDay] = useState<string>('');
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await fetch('/api/hot-stocks', { cache: 'no-store' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to load technical watch');
        if (active) { setRows(data.technical_only_rows || []); setDay(data.trade_date || ''); setError(''); }
      } catch (e) {
        if (active) setError(e instanceof Error ? e.message : 'Unable to load watchlist');
      }
    }
    load();
    const id = window.setInterval(load, 30000);
    return () => { active = false; window.clearInterval(id); };
  }, []);
  return <main style={{ minHeight: '100vh', background: '#080d16', color: '#e6edf7', padding: '32px', fontFamily: 'Inter, system-ui, sans-serif' }}>
    <header style={{ maxWidth: 1100, margin: '0 auto 24px' }}>
      <a href="/" style={{ color: '#79b8ff', textDecoration: 'none' }}>← Prime Technical Scanner</a>
      <h1 style={{ margin: '18px 0 6px', fontSize: 28 }}>Technical-only Watch</h1>
      <p style={{ color: '#91a2ba', margin: 0 }}>Session: {day || '—'} · Technical score ≥ configured threshold · no qualifying fresh news · not a BUY/SELL signal</p>
    </header>
    <section style={{ maxWidth: 1100, margin: '0 auto', border: '1px solid #233149', borderRadius: 14, overflow: 'hidden', background: '#0d1421' }}>
      {error && <p style={{ padding: 20, color: '#ff8799' }}>{error}</p>}
      {!error && rows.length === 0 && <p style={{ padding: 24, color: '#91a2ba' }}>No technical-only candidates available. Apply the Supabase migration and run the pre-open scan.</p>}
      {rows.map((r, i) => <article key={r.id} style={{ display: 'grid', gridTemplateColumns: '42px 1fr 90px 90px', gap: 14, alignItems: 'center', padding: 18, borderBottom: '1px solid #1b2739' }}>
        <strong style={{ color: '#7186a3' }}>{i + 1}</strong>
        <div><strong style={{ fontSize: 16 }}>{r.symbol}</strong><div style={{ color: '#91a2ba', fontSize: 12 }}>{r.company_name || r.symbol}</div><div style={{ color: '#91a2ba', fontSize: 12, marginTop: 6 }}>{(r.reasons || []).join(' · ')}</div></div>
        <div><div style={{ color: '#91a2ba', fontSize: 11 }}>TECH SCORE</div><strong>{r.technical_score}</strong></div>
        <div><div style={{ color: '#91a2ba', fontSize: 11 }}>D-1 MOVE</div><strong>{r.change_percent == null ? '—' : Number(r.change_percent).toFixed(2) + '%'}</strong></div>
      </article>)}
    </section>
    <p style={{ maxWidth: 1100, margin: '14px auto', color: '#7186a3', fontSize: 12 }}>Supplemental research list only. Confirm prices and announcements independently; this list does not issue trading instructions.</p>
  </main>;
}
