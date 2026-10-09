import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const base = (process.env.SUPABASE_URL || "").replace(/\/$/, "");
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!base || !key) {
    return NextResponse.json({ error: "Supabase server environment variables are not configured." }, { status: 500 });
  }
  const headers = { apikey: key, Authorization: "Bearer " + key };
  const endpoint = new URL(base + "/rest/v1/nse_premarket_study");
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const part = (type: string) => parts.find(p => p.type === type)?.value || "00";
  const today = `${part("year")}-${part("month")}-${part("day")}`;
  endpoint.searchParams.set("select", "*");
  endpoint.searchParams.set("trade_date", "eq." + today);
  endpoint.searchParams.set("order", "snapshot_time.desc,preopen_score.desc");
  // One minute may contain the whole F&O universe; the full 09:00–09:08
  // study can exceed PostgREST's default page size. Page through today's rows
  // so the API can report how much of the requested window was actually saved.
  const allRows: Array<Record<string, unknown>> = [];
  const pageSize = 1000;
  for (let offset = 0; offset < 5000; offset += pageSize) {
    const pageUrl = new URL(endpoint.toString());
    pageUrl.searchParams.set("limit", String(pageSize));
    const response = await fetch(pageUrl, {
      headers: { ...headers, Range: `${offset}-${offset + pageSize - 1}` },
      cache: "no-store",
    });
    const body = await response.text();
    if (!response.ok) {
      return NextResponse.json(
        { error: "NSE pre-market study table is unavailable. Apply the nse_premarket_study migration first.", details: body },
        { status: response.status }
      );
    }
    const page = JSON.parse(body) as Array<Record<string, unknown>>;
    allRows.push(...page);
    if (page.length < pageSize) break;
  }
  const latestSnapshot = allRows[0]?.snapshot_time;
  const rows = latestSnapshot ? allRows.filter(row => row.snapshot_time === latestSnapshot) : [];
  const snapshotTimes = [...new Set(allRows.map(row => String(row.snapshot_time ?? "")).filter(Boolean))].sort();
  const snapshotCount = snapshotTimes.length;
  return NextResponse.json(
    {
      snapshot_time: latestSnapshot ?? null,
      rows,
      snapshot_count: snapshotCount,
      window_start: snapshotTimes[0] ?? null,
      window_end: snapshotTimes[snapshotTimes.length - 1] ?? null,
      study_complete: snapshotCount >= 9,
    },
    { headers: { "Cache-Control": "no-store, max-age=0" } }
  );
}
