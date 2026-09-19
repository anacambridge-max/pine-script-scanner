import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

const columns = [
  "id","symbol","instrument_key","signal_type","signal_state","score","grade",
  "ltp","change_percent","entry","stop_loss","target1","target2","risk_reward",
  "setup","cash_trend","futures_trend","oi_setup","ema20_status","vwap_status",
  "rvol","volume_grade","breakout_level","fo_confirmation","is_active",
  "signal_time","last_updated","metadata"
].join(",");

export async function GET(request: Request) {
  const url = new URL(request.url);
  const limit = Math.min(Math.max(Number(url.searchParams.get("limit") || 200), 1), 500);
  const supabaseUrl = process.env.SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!supabaseUrl || !serviceKey) {
    return NextResponse.json({ error: "Supabase server environment variables are not configured." }, { status: 500 });
  }

  const endpoint = new URL(supabaseUrl + "/rest/v1/scanner_signals");
  endpoint.searchParams.set("select", columns);
  endpoint.searchParams.set("order", "signal_time.desc.nullslast");
  endpoint.searchParams.set("limit", String(limit));

  const response = await fetch(endpoint, {
    headers: { apikey: serviceKey, Authorization: "Bearer " + serviceKey },
    cache: "no-store",
  });

  const body = await response.text();
  if (!response.ok) {
    return NextResponse.json({ error: "Supabase signal query failed.", details: body }, { status: response.status });
  }

  return NextResponse.json({ signals: JSON.parse(body) }, { headers: { "Cache-Control": "no-store, max-age=0" } });
}
