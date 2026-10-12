import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const base = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!base || !key) return NextResponse.json({ status: "UNAVAILABLE", error: "Database connection is not configured." }, { status: 503 });
  try {
    const endpoint = new URL(base.replace(/\/$/, "") + "/rest/v1/scanner_heartbeat");
    const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
    endpoint.searchParams.set("select", "last_run_at,status,universe_count,captured_count");
    endpoint.searchParams.set("trade_date", "eq." + today);
    endpoint.searchParams.set("limit", "1");
    const response = await fetch(endpoint, {
      headers: { apikey: key, Authorization: "Bearer " + key },
      cache: "no-store", signal: AbortSignal.timeout(8000),
    });
    if (!response.ok) throw new Error("Heartbeat query failed");
    const [heartbeat] = await response.json();
    const age = heartbeat ? (Date.now() - Date.parse(heartbeat.last_run_at)) / 1000 : Infinity;
    const status = !Number.isFinite(age) || age < -5 || age > 90 ? "OFFLINE" : String(heartbeat.status || "UNKNOWN");
    return NextResponse.json({ status, last_run_at: heartbeat?.last_run_at ?? null, universe_count: heartbeat?.universe_count ?? 0 }, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ status: "UNAVAILABLE", error: "Cannot verify worker health. Check the database connection." }, { status: 503 });
  }
}
