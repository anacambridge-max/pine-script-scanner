type StudyRow = Record<string, unknown>;
const finite = (value: unknown): number | null => {
  const number = Number(value);
  return value === null || value === undefined || value === "" || !Number.isFinite(number) ? null : number;
};

// A pre-open indication can reverse before the open. Only rank symbols with
// repeated, same-direction price and order-book evidence in the saved window.
export function selectMovementCandidates(allRows: StudyRow[], latestSnapshot: string | null) {
  if (!latestSnapshot) return [];
  const bySymbol = new Map<string, StudyRow[]>();
  for (const row of allRows) {
    const symbol = String(row.symbol ?? "").trim().toUpperCase();
    if (!symbol || !row.source_preopen) continue; // OI alone is not price evidence.
    const series = bySymbol.get(symbol) ?? [];
    series.push(row);
    bySymbol.set(symbol, series);
  }
  const candidates: StudyRow[] = [];
  for (const [symbol, series] of bySymbol) {
    const byTime = new Map(series.map(row => [String(row.snapshot_time ?? ""), row]));
    const history = [...byTime.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([, row]) => row);
    const latest = byTime.get(latestSnapshot);
    if (!latest || history.length < 3) continue;
    const gap = finite(latest.indicative_gap_pct);
    const price = finite(latest.indicative_price);
    const buy = finite(latest.buy_qty);
    const sell = finite(latest.sell_qty);
    if (gap === null || price === null || price <= 0 || buy === null || sell === null || buy < 0 || sell < 0) continue;
    if (Math.abs(gap) < 0.75 || Math.abs(gap) > 8 || buy + sell < 1000 || (buy + sell) * price < 1_000_000) continue;
    const direction = gap > 0 ? 1 : -1;
    const share = buy / (buy + sell);
    if (direction === 1 ? share < 0.60 : share > 0.40) continue;
    const recent = history.slice(-3);
    const aligned = recent.filter(row => {
      const g = finite(row.indicative_gap_pct);
      const b = finite(row.buy_qty);
      const s = finite(row.sell_qty);
      if (g === null || b === null || s === null || b + s < 1000) return false;
      return g * direction >= 0.5 && (direction === 1 ? b / (b + s) >= 0.55 : b / (b + s) <= 0.45);
    }).length;
    if (aligned < 2) continue;
    const score = Math.min(100, Math.round(
      Math.min(Math.abs(gap), 4) * 10 +
      Math.min(Math.abs(share - 0.5) * 100, 25) +
      aligned * 8 +
      Math.min(history.length, 9)
    ));
    candidates.push({ ...latest, symbol, movement_direction: direction === 1 ? "UP WATCH" : "DOWN WATCH",
      movement_score: score, aligned_snapshots: aligned, observed_snapshots: history.length });
  }
  return candidates.sort((a, b) => Number(b.movement_score) - Number(a.movement_score) || String(a.symbol).localeCompare(String(b.symbol))).slice(0, 20);
}

