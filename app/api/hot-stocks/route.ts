import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceKey) {
    return NextResponse.json({ error: "Supabase server environment variables are not configured." }, { status: 500 });
  }

  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now);
  const part = (type: string) => parts.find(p => p.type === type)?.value || "00";
  const target = `${part("year")}-${part("month")}-${part("day")}`;

  // The database row represents the completed session used by the
  // morning scan. Therefore, before today's open, the latest valid row is
  // usually yesterday (or the latest prior trading session), not today's date.
  // Resolve the latest stored analysis date first so the UI never shows an
  // empty list simply because the calendar date changed.
  const latestEndpoint = new URL(supabaseUrl + "/rest/v1/morning_hot_stocks");
  latestEndpoint.searchParams.set("select", "trade_date");
  latestEndpoint.searchParams.set("trade_date", "lte." + target);
  latestEndpoint.searchParams.set("order", "trade_date.desc");
  latestEndpoint.searchParams.set("limit", "1");

  const latestResponse = await fetch(latestEndpoint, {
    headers: { apikey: serviceKey, Authorization: "Bearer " + serviceKey },
    cache: "no-store",
  });
  const latestBody = await latestResponse.text();
  if (!latestResponse.ok) {
    return NextResponse.json(
      { error: "Supabase latest hot-stock date query failed.", details: latestBody },
      { status: latestResponse.status }
    );
  }

  const latestRows = JSON.parse(latestBody);
  if (!latestRows.length) {
    return NextResponse.json(
      { trade_date: null, rows: [] },
      { headers: { "Cache-Control": "no-store, max-age=0" } }
    );
  }

  const analysisDate = latestRows[0].trade_date;
  const endpoint = new URL(supabaseUrl + "/rest/v1/morning_hot_stocks");
  endpoint.searchParams.set("select", "*");
  endpoint.searchParams.set("trade_date", "eq." + analysisDate);
  endpoint.searchParams.set("order", "score.desc");
  endpoint.searchParams.set("limit", "10");

  const response = await fetch(endpoint, {
    headers: { apikey: serviceKey, Authorization: "Bearer " + serviceKey },
    cache: "no-store",
  });
  const body = await response.text();
  if (!response.ok) {
    return NextResponse.json(
      { error: "Supabase morning hot-stocks query failed.", details: body },
      { status: response.status }
    );
  }

  return NextResponse.json(
    { trade_date: analysisDate, rows: JSON.parse(body) },
    { headers: { "Cache-Control": "no-store, max-age=0" } }
  );
}
