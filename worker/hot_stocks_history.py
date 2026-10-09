"""Local SQLite history for Hot Stocks and technical-only candidates."""
from __future__ import annotations
import csv, sqlite3
from pathlib import Path
from datetime import date, timedelta
from typing import Iterable, Any

class HotStockHistory:
    def __init__(self, path: str | Path = "data/hot_stocks_history.sqlite3"):
        self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS candidates (
              trade_date TEXT NOT NULL, symbol TEXT NOT NULL, list_type TEXT NOT NULL,
              technical_score REAL, news_score REAL, final_score REAL, direction TEXT,
              headline TEXT, source TEXT, published_ist TEXT, close REAL,
              next_day_move_pct REAL, next_day_range_pct REAL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY(trade_date,symbol,list_type))""")
    def save(self, rows: Iterable[dict[str, Any]], trade_date: str, list_type: str) -> None:
        with sqlite3.connect(self.path) as db:
            for r in rows:
                db.execute("""INSERT INTO candidates
                  (trade_date,symbol,list_type,technical_score,news_score,final_score,direction,
                   headline,source,published_ist,close)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(trade_date,symbol,list_type) DO UPDATE SET
                   technical_score=excluded.technical_score,news_score=excluded.news_score,
                   final_score=excluded.final_score,direction=excluded.direction,
                   headline=excluded.headline,source=excluded.source,
                   published_ist=excluded.published_ist,close=excluded.close""",
                  (trade_date,r.get("symbol"),list_type,r.get("technical_score"),r.get("news_score"),
                   r.get("score",r.get("final_score")),r.get("direction"),r.get("news_summary"),
                   r.get("news_source"),r.get("published_ist"),r.get("close")))
    def export_csv(self, path: str | Path = "data/hot_stocks_history.csv") -> str:
        with sqlite3.connect(self.path) as db:
            rows=db.execute("SELECT * FROM candidates ORDER BY trade_date DESC,final_score DESC").fetchall()
            headers=[x[0] for x in db.execute("SELECT * FROM candidates LIMIT 0").description]
        out=Path(path); out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("w",newline="",encoding="utf-8") as f:
            writer=csv.writer(f); writer.writerow(headers); writer.writerows(rows)
        return str(out)
    def backtest(self, min_move_pct: float = 1.5) -> dict[str, Any]:
        with sqlite3.connect(self.path) as db:
            rows=db.execute("""SELECT COUNT(*), SUM(CASE WHEN ABS(next_day_move_pct)>=? THEN 1 ELSE 0 END),
              SUM(CASE WHEN next_day_range_pct>=? THEN 1 ELSE 0 END)
              FROM candidates WHERE next_day_move_pct IS NOT NULL""",(min_move_pct,min_move_pct)).fetchone()
        return {"evaluated":rows[0] or 0,"absolute_move_hits":rows[1] or 0,
                "range_expansion_hits":rows[2] or 0,
                "note":"Populate next_day_move_pct and next_day_range_pct after the next session to evaluate outcomes."}
