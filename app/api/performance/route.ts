import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

type Outcome = { version?: number; status?: string; first_hit?: string | null; returns_pct?: Record<string, number> };
type Row = { score: number | null; signal_time: string; metadata?: { outcome?: Outcome } };

function median(values: number[]) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return Number((sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2).toFixed(2));
}

function summarize(rows: Row[]) {
  const tracked = rows.filter(row => row.metadata?.outcome?.version === 1);
  const complete = tracked.filter(row => row.metadata?.outcome?.status === "COMPLETE");
  const firstHit = { target: 0, stop: 0, ambiguous: 0, neither: 0 };
  for (const row of complete) {
    const hit = row.metadata?.outcome?.first_hit;
    if (hit === "TARGET") firstHit.target++;
    else if (hit === "STOP") firstHit.stop++;
    else if (hit === "AMBIGUOUS") firstHit.ambiguous++;
    else firstHit.neither++;
  }
  const medianReturnPct: Record<string, number | null> = {};
  for (const horizon of [15, 30, 60]) {
    medianReturnPct[String(horizon)] = median(complete.map(row => row.metadata?.outcome?.returns_pct?.[String(horizon)]).filter((n): n is number => typeof n === "number" && Number.isFinite(n)));
  }
  const scoreBands = [
    { label: "<70", min: -Infinity, max: 70 },
    { label: "70–79", min: 70, max: 80 },
    { label: "80–89", min: 80, max: 90 },
    { label: "90+", min: 90, max: Infinity },
  ].map(band => {
    const sample = complete.filter(row => Number(row.score) >= band.min && Number(row.score) < band.max);
    return { label: band.label, sample: sample.length, medianReturn60Pct: median(sample.map(row => row.metadata?.outcome?.returns_pct?.["60"]).filter((n): n is number => typeof n === "number" && Number.isFinite(n))) };
  });
  return { tracked: tracked.length, complete: complete.length, pending: tracked.length - complete.length, firstHit, medianReturnPct, scoreBands, sufficientSample: complete.length >= 30 };
}

export async function GET() {
  const base = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!base || !key) return NextResponse.json({ error: "Database connection is not configured." }, { status: 503 });
  const since = new Date(Date.now() - 30 * 86400000).toISOString();
  const rows: Row[] = [];
  try {
    for (let offset = 0; offset < 5000; offset += 1000) {
      const url = new URL(base.replace(/\/$/, "") + "/rest/v1/scanner_signals");
      url.searchParams.set("select", "score,signal_time,metadata");
      url.searchParams.set("signal_time", "gte." + since);
      url.searchParams.set("signal_state", "eq.CONFIRMED");
      url.searchParams.set("setup", "eq.STANDARD BREAK");
      url.searchParams.set("metadata->>timeframe", "eq.3");
      url.searchParams.set("order", "signal_time.desc");
      url.searchParams.set("limit", "1000");
      url.searchParams.set("offset", String(offset));
      const response = await fetch(url, { headers: { apikey: key, Authorization: "Bearer " + key }, cache: "no-store", signal: AbortSignal.timeout(8000) });
      if (!response.ok) throw new Error("Performance query failed");
      const page = await response.json() as Row[];
      rows.push(...page);
      if (page.length < 1000) break;
    }
    return NextResponse.json({ windowDays: 30, ...summarize(rows) }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Performance data is temporarily unavailable." }, { status: 503 });
  }
}
