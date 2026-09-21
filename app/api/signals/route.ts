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
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  endpoint.searchParams.set("select", columns);
  // Dashboard is intentionally limited to the current scanner mode:
  // confirmed 3m first PDH/PDL breaks only. This prevents legacy 1m/5m,
  // MASTER CANDLE and other historical rows from appearing in "ALL TODAY".
  endpoint.searchParams.set("signal_state", "eq.CONFIRMED");
  endpoint.searchParams.set("setup", "eq.STANDARD BREAK");
  // Hard filter the dashboard to the current scanner's ONLY supported timeframe.
  // PostgREST JSON path syntax: metadata->>timeframe=eq.3
  endpoint.searchParams.set("metadata->>timeframe", "eq.3");
  endpoint.searchParams.set("signal_time", `gte.${today}T00:00:00`);
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
