type ConfirmedStock = {symbol: string; signal_state: string | null};
type Section = {name: string; symbols: string[]};
const normalize = (symbol: string) => symbol.trim().toUpperCase();

export function buildCommonStockRows(signals: ConfirmedStock[], sections: Section[]) {
  const confirmed = new Set(signals.filter(row => row.signal_state === "CONFIRMED").map(row => normalize(row.symbol)).filter(Boolean));
  const matches = new Map<string, Set<string>>();
  for (const section of sections) {
    for (const raw of section.symbols) {
      const symbol = normalize(raw);
      if (!confirmed.has(symbol)) continue;
      const headings = matches.get(symbol) ?? new Set<string>(["CONFIRMED SIGNALS"]);
      headings.add(section.name);
      matches.set(symbol, headings);
    }
  }
  return [...matches].filter(([, headings]) => headings.size >= 2)
    .map(([symbol, headings]) => ({symbol, sections: [...headings], count: headings.size}))
    .sort((a,b) => b.count-a.count || a.symbol.localeCompare(b.symbol));
}
