"""Numeric cash-chart study for the five user-supplied chart symbols."""
import json, os, shlex, gzip
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import quote
import requests
import pandas as pd
from engine.daily_context import daily_context
from worker.market_context import candle_evidence
from worker.upstox_feed import UpstoxV3Feed

def main():
    for line in Path(".env").read_text().splitlines():
        line=line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key,value=line.removeprefix("export ").split("=",1)
        parts=shlex.split(value,comments=True)
        if parts: os.environ.setdefault(key.strip(),parts[0])
    day=datetime.now(ZoneInfo("Asia/Kolkata")).date()
    headers={"Authorization":"Bearer "+os.environ["UPSTOX_ACCESS_TOKEN"]}
    response=requests.get("https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz",timeout=60)
    response.raise_for_status()
    master=json.loads(gzip.decompress(response.content))
    symbols={"IRFC","DELHIVERY","NUVAMA","WELCORP","ZEEL"}
    instruments=[x for x in master if x.get("segment")=="NSE_EQ" and x.get("instrument_type")=="EQ" and x.get("trading_symbol") in symbols]
    histories=UpstoxV3Feed(os.environ["UPSTOX_ACCESS_TOKEN"],[x["instrument_key"] for x in instruments]).get_daily_histories(90,day-timedelta(days=1))
    result=[]
    for item in instruments:
        key=item["instrument_key"]
        context=daily_context(histories[key],day.isoformat()) if key in histories else {"status":"MISSING"}
        response=requests.get("https://api.upstox.com/v3/historical-candle/intraday/"+quote(key,safe="")+"/minutes/3",headers=headers,timeout=20)
        response.raise_for_status()
        candles=response.json().get("data",{}).get("candles",[])
        candles=sorted([c for c in candles if pd.Timestamp(c[0]).date()==day],key=lambda c:c[0])
        opening=candles[0] if candles else None
        closed=None
        if candles:
            closed=candle_evidence({"ohlc":{"open":candles[0][1],"high":max(c[2] for c in candles),"low":min(c[3] for c in candles)},"last_price":candles[-1][4],"prev_close_price":histories[key].iloc[-1].close},context)
        row={"symbol":item["trading_symbol"],"daily_context":context,"opening_3m":opening,"session_from_3m":closed,"candles":len(candles)}
        result.append(row)
        print(json.dumps(row,default=str))
    Path("data/chart-stock-study.json").write_text(json.dumps(result,indent=2,default=str))
if __name__=="__main__": main()
