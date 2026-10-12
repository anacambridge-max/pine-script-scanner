import { NextResponse } from "next/server";
export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const base = process.env.SUPABASE_URL?.replace(/\/$/, "");
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!base || !key) return NextResponse.json({error: "Market context is not configured."}, {status: 500});
  const today = new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Kolkata"}).format(new Date());
  const endpoint = new URL(`${base}/rest/v1/scanner_market_context`);
  endpoint.searchParams.set("select", "symbol,observed_at,daily_context,sector_context,market_evidence");
  endpoint.searchParams.set("trade_date", `eq.${today}`);
  endpoint.searchParams.set("order", "symbol.asc");
  endpoint.searchParams.set("limit", "500");
  try {
    const response = await fetch(endpoint, {headers: {apikey: key, Authorization: `Bearer ${key}`}, cache: "no-store"});
    if (!response.ok) return NextResponse.json({error: "Market context query failed; daily/sector/OI evidence is unavailable."}, {status: 503});
    return NextResponse.json({trade_date: today, rows: await response.json()}, {headers: {"Cache-Control": "no-store"}});
  } catch {
    return NextResponse.json({error: "Market context could not refresh."}, {status: 503});
  }
}
