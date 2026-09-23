import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const supabaseUrl = process.env.SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!supabaseUrl || !serviceKey) {
    return NextResponse.json({ error: "Supabase server environment variables are not configured." }, { status: 500 });
  }

  const target = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  const endpoint = new URL(supabaseUrl + "/rest/v1/next_day_watchlist");
  endpoint.searchParams.set("select", "*");
  endpoint.searchParams.set("target_date", "eq." + target);
  endpoint.searchParams.set("order", "direction.asc,score.desc");
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
