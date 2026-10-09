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
  endpoint.searchParams.set("limit", "200");
  const response = await fetch(endpoint, { headers, cache: "no-store" });
  const body = await response.text();
  if (!response.ok) {
    return NextResponse.json(
      { error: "NSE pre-market study table is unavailable. Apply the nse_premarket_study migration first.", details: body },
      { status: response.status }
    );
  }
  const allRows = JSON.parse(body) as Array<Record<string, unknown>>;
  const latestSnapshot = allRows[0]?.snapshot_time;
  const rows = latestSnapshot ? allRows.filter(row => row.snapshot_time === latestSnapshot) : [];
  return NextResponse.json(
    { snapshot_time: latestSnapshot ?? null, rows },
    { headers: { "Cache-Control": "no-store, max-age=0" } }
  );
}
