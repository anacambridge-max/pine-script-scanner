"""Same-day stock-watch and earnings coverage from Upstox and Moneycontrol.

Publisher articles are contextual evidence only. They never create or alter a
confirmed scanner signal.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests


IST = ZoneInfo("Asia/Kolkata")
INDEX_PAGES = (
    "https://upstox.com/news/market-news/stocks/",
    "https://www.moneycontrol.com/news/tags/stocks-to-watch.html",
    "https://www.moneycontrol.com/news/business/markets/",
    "https://www.moneycontrol.com/markets/earnings/latest-results/",
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PrimeScanner/1.0; +https://pine-script-scanner.vercel.app)",
    "Accept-Language": "en-IN,en;q=0.9",
}
RELEVANT_TITLE = re.compile(r"stocks?\s+to\s+watch|stocks?\s+in\s+focus|results?\s+today|quarterly\s+(?:earnings|results)|latest\s+results|earnings", re.I)
ALLOWED = ("upstox.com", "moneycontrol.com")


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.meta: dict[str, str] = {}
        self.paragraphs: list[str] = []
        self._href = ""
        self._anchor: list[str] = []
        self._p_depth = 0
        self._p: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
            value = attrs.get("content")
            if key and value:
                self.meta[key] = value
        if tag == "time" and attrs.get("datetime"):
            self.meta.setdefault("time:datetime", attrs["datetime"])
        if tag == "a":
            self._href = attrs.get("href") or ""
            self._anchor = []
        if tag in {"p", "h1", "h2", "h3", "h4"}:
            self._p_depth += 1

    def handle_data(self, data):
        if self._skip:
            return
        if self._href:
            self._anchor.append(data)
        if self._p_depth:
            self._p.append(data)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip = max(0, self._skip - 1)
        if tag == "a" and self._href:
            title = re.sub(r"\s+", " ", " ".join(self._anchor)).strip()
            if title:
                self.links.append((self._href, title))
            self._href, self._anchor = "", []
        if tag in {"p", "h1", "h2", "h3", "h4"} and self._p_depth:
            value = re.sub(r"\s+", " ", " ".join(self._p)).strip()
            if value:
                self.paragraphs.append(value)
            self._p_depth = 0
            self._p = []


def _fetch(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=10)
    response.raise_for_status()
    return response.text


def _published_from_page(page: _Page) -> datetime | None:
    raw = next((page.meta[key] for key in (
        "article:published_time", "og:article:published_time", "datepublished",
        "publishdate", "pubdate", "time:datetime",
    ) if page.meta.get(key)), None)
    if raw:
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return stamp.replace(tzinfo=IST) if stamp.tzinfo is None else stamp.astimezone(IST)
        except ValueError:
            parsed = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", raw)
            if parsed:
                return datetime(int(parsed[1]), int(parsed[2]), int(parsed[3]), tzinfo=IST)
    return None


def _aliases(instrument: dict) -> list[str]:
    symbol = str(instrument.get("trading_symbol") or "").upper()
    company = str(instrument.get("company_name") or "")
    aliases = [symbol, company]
    alias_map = {
        "DELHIVERY": ["Delhivery Limited", "Delhivery"], "DIXON": ["Dixon Technologies"],
        "JIOFIN": ["Jio Financial Services"], "JPL": ["Jio Platforms"],
        "RELIANCE": ["Reliance Industries"], "M&M": ["Mahindra and Mahindra", "Mahindra & Mahindra"],
        "BAJAJFINSV": ["Bajaj Finserv"], "POLICYBZR": ["PB Fintech", "Policybazaar"],
        "TATAMOTORS": ["Tata Motors Passenger Vehicles", "Tata Motors"],
        "TATAMOTORSPV": ["Tata Motors Passenger Vehicles"], "TATAMTRDVR": ["Tata Motors"],
        "MARUTI": ["Maruti Suzuki India"], "HDFCBANK": ["HDFC Bank"],
        "BANKBARODA": ["Bank of Baroda"], "COALINDIA": ["Coal India"],
        "IOC": ["Indian Oil Corporation", "Indian Oil"], "NTPC": ["NTPC Limited"],
        "BEL": ["Bharat Electronics"], "NCC": ["NCC Limited"],
    }
    aliases.extend(alias_map.get(symbol, []))
    cleaned = []
    for alias in aliases:
        value = re.sub(r"[^a-z0-9]+", " ", alias.lower()).strip()
        value = re.sub(r"\b(limited|ltd|india|inc|corporation|corp|company|co|plc)\b", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        if len(value) >= 4 and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _matches(blob: str, aliases: list[str]) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", " ", blob.lower())
    return any(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized) for alias in aliases)


def _classify(title: str, paragraph: str, source: str) -> str:
    text = f"{title} {paragraph}".lower()
    if source == "Moneycontrol" and re.search(r"results? today|quarterly (?:earnings|results)|will release .* earnings|announc(?:e|ing) .* results|\bq[1-4]\b", text):
        return "EARNINGS / RESULTS"
    return "STOCKS TO WATCH"


def fetch_daily_stock_articles(instruments: list[dict], now: datetime | None = None) -> dict[str, list[dict]]:
    """Discover relevant publisher pages and keep only pages published today IST."""
    now = now or datetime.now(IST)
    today = now.astimezone(IST).date()
    candidates: dict[str, tuple[str, str, str]] = {}
    for index_url in INDEX_PAGES:
        try:
            page = _Page()
            page.feed(_fetch(index_url))
            for raw_url, title in page.links:
                url = urljoin(index_url, raw_url).split("#", 1)[0]
                host = urlparse(url).hostname or ""
                if not any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED):
                    continue
                if url.rstrip("/") == index_url.rstrip("/") or not RELEVANT_TITLE.search(title):
                    continue
                source = "Upstox" if "upstox.com" in host else "Moneycontrol"
                candidates[url] = (title[:300], source, index_url)
        except Exception as exc:
            print(f"[DAILY ARTICLES WARNING] index {index_url}: {type(exc).__name__}")

    # A direct current-day article may not appear in every index crawl. Include
    # article URLs surfaced by the publishers' article discovery pages only;
    # the supplied dated URLs are not used as permanent daily inputs.
    pages: dict[str, tuple[str, _Page, date]] = {}

    def load_article(entry):
        url, (title, source, _) = entry
        try:
            page = _Page()
            page.feed(_fetch(url))
            published = _published_from_page(page)
            title = page.meta.get("og:title") or page.meta.get("twitter:title") or title
            if published and published.date() == today and published <= now.astimezone(IST):
                return url, (title[:300], source, page, published)
        except Exception as exc:
            print(f"[DAILY ARTICLES WARNING] article {url}: {type(exc).__name__}")
        return url, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for url, loaded in pool.map(load_article, list(candidates.items())[:40]):
            if loaded:
                pages[url] = loaded

    result: dict[str, list[dict]] = {}
    for instrument in instruments:
        symbol = str(instrument.get("trading_symbol") or "")
        aliases = _aliases(instrument)
        matched = []
        for url, (title, source, page, published) in pages.items():
            relevant_paragraphs = [paragraph for paragraph in page.paragraphs if _matches(paragraph, aliases)]
            title_match = _matches(title, aliases)
            if not relevant_paragraphs and not title_match:
                continue
            context = " ".join(relevant_paragraphs[:3]) or title
            matched.append({
                "title": title, "url": url, "published_at": published.isoformat(),
                "source": source, "kind": _classify(title, context, source),
                "context": context[:700], "impact": "UNVERIFIED — ARTICLE MENTION IS NOT A TRADE SIGNAL",
            })
        if matched:
            result[symbol] = sorted(matched, key=lambda item: (item["kind"] != "EARNINGS / RESULTS", item["published_at"]), reverse=True)[:8]
    return result
