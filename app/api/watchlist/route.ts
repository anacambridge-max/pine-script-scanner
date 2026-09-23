import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceKey) {
    return NextResponse.json({ error: "Supabase server environment variables are not configured." }, { status: 500 });
  }

  // The worker switches to the NEXT trading session after 15:35 IST.
  // The dashboard must query the same target date; querying "today" after
  // the close would hide the rows generated for tomorrow.
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(now);
  const part = (type: string) => parts.find(p => p.type === type)?.value || "00";
  const y = Number(part("year"));
  const m = Number(part("month"));
  const d = Number(part("day"));
  const hour = Number(part("hour"));
  const minute = Number(part("minute"));
  const local = new Date(Date.UTC(y, m - 1, d));
  if (hour > 15 || (hour === 15 && minute >= 35)) {
    local.setUTCDate(local.getUTCDate() + 1);
    while (local.getUTCDay() === 0 || local.getUTCDay() === 6) {
      local.setUTCDate(local.getUTCDate() + 1);
    }
  }
  const target = local.toISOString().slice(0, 10);

  const endpoint = new URL(supabaseUrl + "/rest/v1/next_day_watchlist");
  endpoint.searchParams.set("select", "*");
  endpoint.searchParams.set("target_date", "eq." + target);
  endpoint.searchParams.set("order", "score.desc");
  endpoint.searchParams.set("limit", "20");

  const response = await fetch(endpoint, {
    headers: { apikey: serviceKey, Authorization: "Bearer " + serviceKey },
    cache: "no-store",
  });
  const body = await response.text();
  if (!response.ok) {
    return NextResponse.json({ error: "Supabase watchlist query failed.", details: body }, { status: response.status });
  }
  return NextResponse.json({ target_date: target, rows: JSON.parse(body) }, { headers: { "Cache-Control": "no-store, max-age=0" } });
}
