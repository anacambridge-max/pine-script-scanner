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

  const endpoint = new URL(supabaseUrl + "/rest/v1/morning_hot_stocks");
  endpoint.searchParams.set("select", "*");
  endpoint.searchParams.set("trade_date", "eq." + target);
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
    { trade_date: target, rows: JSON.parse(body) },
    { headers: { "Cache-Control": "no-store, max-age=0" } }
  );
}
