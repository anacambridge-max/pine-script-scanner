"""Fresh-news qualification helpers for Today's Hot Stocks only.

BUY/SELL confirmed signal code must not import this module.
"""
from __future__ import annotations
import hashlib, json, re, sqlite3
from datetime import datetime, time, timedelta, date
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_MAX_AGE_HOURS = 24
RECENCY = ((6, 1.0), (12, 0.8), (24, 0.6))
TIER_POINTS = {"MATERIAL EVENT": 28, "STRONG CATALYST": 21, "GENERAL MENTION": 7}
MATERIAL = ("order win", "large order", "contract win", "acquisition", "merger", "buyback", "bonus issue", "dividend", "results", "earnings", "नया ऑर्डर", "बड़ा ऑर्डर", "अधिग्रहण", "नतीजे")
CATALYST = ("upgrade", "downgrade", "approval", "launch", "funding", "stake sale", "partnership", "breakout", "अपग्रेड", "मंजूरी", "लॉन्च", "साझेदारी")
NEGATIVE = ("downgrade", "fraud", "default", "loss widens", "probe", "penalty", "ban", "गिरावट", "जांच", "जुर्माना", "डिफॉल्ट")
POSITIVE = ("order win", "upgrade", "approval", "profit rises", "buyback", "bonus", "मंजूरी", "नया ऑर्डर", "मुनाफा बढ़ा")

def parse_published_at(value: Any) -> datetime | None:
    """Parse RFC822, ISO8601 and common RSS dates; naive timestamps are rejected."""
    if not value or not isinstance(value, str) or not value.strip(): return None
    raw=value.strip()
    try:
        dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
    except ValueError:
        try: dt=parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError): return None
    if dt is None or dt.tzinfo is None: return None
    return dt.astimezone(IST)

def freshness_weight(published: datetime | None, now: datetime | None = None,
                     max_age_hours: int = DEFAULT_MAX_AGE_HOURS) -> float:
    if published is None or published.tzinfo is None: return 0.0
    now=(now or datetime.now(IST)).astimezone(IST); published=published.astimezone(IST)
    if published > now: return 0.0
    age=(now-published).total_seconds()/3600
    # Allow prior-session-to-preopen window across weekends/holidays, but never beyond 7 days.
    if now.time() <= time(9,0) and published.time() >= time(15,30) and published.date() < now.date():
        days=(now.date()-published.date()).days
        if days <= 4: return 1.0 if age <= max_age_hours else 0.6
    if age > max_age_hours: return 0.0
    for limit, weight in RECENCY:
        if age <= limit: return weight
    return 0.6

def _norm(text: str) -> str:
    return re.sub(r"[^\w&]+", " ", (text or "").casefold(), flags=re.UNICODE).strip()

def alias_matches(text: str, aliases: list[str]) -> bool:
    """Word-boundary alias match; avoids e.g. 'HAL' matching 'HALO'."""
    hay=(text or "").casefold()
    for alias in aliases:
        alias=(alias or "").strip()
        if not alias: continue
        pattern=r"(?<![\w])"+re.escape(alias.casefold())+r"(?![\w])"
        if re.search(pattern, hay, flags=re.UNICODE): return True
    return False

def classify_direction(text: str) -> str:
    t=(text or "").casefold()
    pos=any(k in t for k in POSITIVE); neg=any(k in t for k in NEGATIVE)
    return "mixed" if pos and neg else "positive" if pos else "negative" if neg else "neutral"

def catalyst_tier(text: str) -> tuple[str, int]:
    t=(text or "").casefold()
    if any(k in t for k in MATERIAL): return "MATERIAL EVENT", TIER_POINTS["MATERIAL EVENT"]
    if any(k in t for k in CATALYST): return "STRONG CATALYST", TIER_POINTS["STRONG CATALYST"]
    return "GENERAL MENTION", TIER_POINTS["GENERAL MENTION"]

def score_news(text: str, published_at: Any, now: datetime | None = None) -> dict[str, Any]:
    published=parse_published_at(published_at)
    weight=freshness_weight(published, now)
    tier, base=catalyst_tier(text)
    score=round(min(30, base*weight)) if weight else 0
    return {"news_score": score, "tier": tier, "direction": classify_direction(text),
            "published_ist": published.isoformat() if published else None,
            "freshness_weight": weight, "reason": tier if score else "Missing/invalid/stale publication time"}

class SeenNewsStore:
    """SQLite dedup ledger. DB is local runtime state and should not be committed."""
    def __init__(self, path: str | Path = "data/hot_stocks_news.sqlite3"):
        self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS seen_news (
                hash TEXT NOT NULL, stock TEXT NOT NULL, first_seen_date TEXT NOT NULL,
                source TEXT NOT NULL, PRIMARY KEY(hash, stock))""")
            db.execute("DELETE FROM seen_news WHERE first_seen_date < ?", ((date.today()-timedelta(days=10)).isoformat(),))
    @staticmethod
    def fingerprint(url: str, headline: str) -> str:
        value=(url.strip().lower() if url else re.sub(r"\W+"," ",headline.casefold()).strip())
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    def is_new(self, url: str, headline: str, stock: str, source: str = "") -> bool:
        key=self.fingerprint(url, headline); today=date.today().isoformat()
        with sqlite3.connect(self.path) as db:
            cur=db.execute("INSERT OR IGNORE INTO seen_news(hash,stock,first_seen_date,source) VALUES(?,?,?,?)",
                           (key, stock.upper(), today, source))
            return cur.rowcount == 1

def qualifies(tech_score: float, news_score: float, min_tech_score: float = 55) -> bool:
    return tech_score >= min_tech_score and news_score > 0

def load_aliases(path: str | Path = "worker/stock_aliases.json") -> dict[str, list[str]]:
    with open(path, encoding="utf-8") as f:
        data=json.load(f)
    return {str(k): list(v) for k,v in data.items() if isinstance(v, list)}
