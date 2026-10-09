import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const IST = "Asia/Kolkata";
const EXPECTED_MINUTES = Array.from({ length: 9 }, (_, minute) => `09:${String(minute).padStart(2, "0")}`);

function istClock(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: IST, hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const hour = parts.find((part) => part.type === "hour")?.value;
  const minute = parts.find((part) => part.type === "minute")?.value;
  return hour && minute ? `${hour}:${minute}` : null;
}

export async function GET() {
  const base = (process.env.SUPABASE_URL || "").replace(/\/$/, "");
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!base || !key) {
    return NextResponse.json({ error: "Supabase server environment variables are not configured." }, { status: 500 });
  }

  const headers = { apikey: key, Authorization: "Bearer " + key };
  const endpoint = new URL(base + "/rest/v1/nse_premarket_study");
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: IST, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const part = (type: string) => parts.find((p) => p.type === type)?.value || "00";
  const today = `${part("year")}-${part("month")}-${part("day")}`;

  endpoint.searchParams.set("select", "*");
  endpoint.searchParams.set("trade_date", "eq." + today);
  endpoint.searchParams.set("order", "snapshot_time.desc,preopen_score.desc");

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
        { error: "NSE pre-market study table is unavailable. Check the nse_premarket_study migration.", details: body },
        { status: response.status }
      );
    }
    const page = JSON.parse(body) as Array<Record<string, unknown>>;
    allRows.push(...page);
    if (page.length < pageSize) break;
  }

  const snapshotTimes = [...new Set(allRows.map((row) => String(row.snapshot_time ?? "")).filter(Boolean))]
    .sort((a, b) => new Date(a).getTime() - new Date(b).getTime());
  const capturedMinutes = new Set(snapshotTimes.map(istClock).filter((value): value is string => Boolean(value)));
  const missingMinutes = EXPECTED_MINUTES.filter((minute) => !capturedMinutes.has(minute));
  const latestSnapshot = snapshotTimes[snapshotTimes.length - 1] ?? null;
  const rows = latestSnapshot
    ? allRows.filter((row) => String(row.snapshot_time ?? "") === latestSnapshot)
      .sort((a, b) => Number(b.preopen_score ?? 0) - Number(a.preopen_score ?? 0))
    : [];

  return NextResponse.json({
    trade_date: today,
    snapshot_time: latestSnapshot,
    rows,
    snapshot_count: capturedMinutes.size,
    window_start: snapshotTimes[0] ?? null,
    window_end: latestSnapshot,
    study_complete: missingMinutes.length === 0,
    missing_minutes: missingMinutes,
    source_links: {
      preopen: "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market",
      oi_spurts: "https://www.nseindia.com/market-data/oi-spurts",
    },
  }, { headers: { "Cache-Control": "no-store, max-age=0" } });
}
