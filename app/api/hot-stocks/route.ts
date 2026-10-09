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
  // Only expose a scan created today in IST. If the worker has not completed
  // today's scan, do not keep presenting yesterday's candidates as today's list.
  const todayStartUtc = new Date(`${target}T00:00:00+05:30`).toISOString();
  const tomorrowStartUtc = new Date(Date.parse(`${target}T00:00:00+05:30`) + 24 * 60 * 60 * 1000).toISOString();

  // The morning scan stores the completed session date (yesterday) in
  // trade_date. Multiple runs on the same morning can therefore have the
  // same trade_date. Select the LATEST RUN by created_at so the dashboard
  // never keeps showing an older pre-fix list.
  const latestEndpoint = new URL(supabaseUrl + "/rest/v1/morning_hot_stocks");
  latestEndpoint.searchParams.set("select", "trade_date,created_at");
  latestEndpoint.searchParams.set("trade_date", "lte." + target);
  latestEndpoint.searchParams.set("and", `(created_at.gte.${todayStartUtc},created_at.lt.${tomorrowStartUtc})`);
  latestEndpoint.searchParams.set("order", "created_at.desc");
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

  // Technical-only candidates can exist on a date with zero Hot Stocks. Choose
  // the newest run across both tables so the dashboard never falls back to an
  // older hot-stock date merely because today's news gate rejected everything.
  const latestTechnicalEndpoint = new URL(supabaseUrl + "/rest/v1/morning_technical_watch");
  latestTechnicalEndpoint.searchParams.set("select", "trade_date,created_at");
  latestTechnicalEndpoint.searchParams.set("trade_date", "lte." + target);
  latestTechnicalEndpoint.searchParams.set("and", `(created_at.gte.${todayStartUtc},created_at.lt.${tomorrowStartUtc})`);
  latestTechnicalEndpoint.searchParams.set("order", "created_at.desc");
  latestTechnicalEndpoint.searchParams.set("limit", "1");
  const latestTechnicalResponse = await fetch(latestTechnicalEndpoint, {
    headers: { apikey: serviceKey, Authorization: "Bearer " + serviceKey },
    cache: "no-store",
  });
  let latestTechnicalRows: Array<{trade_date: string; created_at: string}> = [];
  if (latestTechnicalResponse.ok) {
    latestTechnicalRows = await latestTechnicalResponse.json();
  } else {
    console.warn("Technical-only latest-date query failed:", await latestTechnicalResponse.text());
  }

  const latestCandidate = [...latestRows, ...latestTechnicalRows]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0];
  if (!latestCandidate) {
    return NextResponse.json(
      { trade_date: null, rows: [], technical_only_rows: [] },
      { headers: { "Cache-Control": "no-store, max-age=0" } }
    );
  }

  const analysisDate = latestCandidate.trade_date;
  const endpoint = new URL(supabaseUrl + "/rest/v1/morning_hot_stocks");
  endpoint.searchParams.set("select", "*");
  endpoint.searchParams.set("trade_date", "eq." + analysisDate);
  endpoint.searchParams.set("technical_score", "gte.55");
  endpoint.searchParams.set("news_score", "gt.0");
  endpoint.searchParams.set("published_ist", "not.is.null");
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

  const technicalEndpoint = new URL(supabaseUrl + "/rest/v1/morning_technical_watch");
  technicalEndpoint.searchParams.set("select", "*");
  technicalEndpoint.searchParams.set("trade_date", "eq." + analysisDate);
  technicalEndpoint.searchParams.set("order", "score.desc");
  technicalEndpoint.searchParams.set("limit", "10");
  const technicalResponse = await fetch(technicalEndpoint, {
    headers: { apikey: serviceKey, Authorization: "Bearer " + serviceKey },
    cache: "no-store",
  });
  let technicalOnlyRows: unknown[] = [];
  if (technicalResponse.ok) {
    technicalOnlyRows = await technicalResponse.json();
  } else {
    // A missing optional table must not take down the live signals or hot-stock list.
    console.warn("Technical-only watch table is unavailable:", await technicalResponse.text());
  }

  return NextResponse.json(
    { trade_date: analysisDate, rows: JSON.parse(body), technical_only_rows: technicalOnlyRows },
    { headers: { "Cache-Control": "no-store, max-age=0" } }
  );
}
