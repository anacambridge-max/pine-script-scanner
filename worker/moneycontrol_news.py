from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import urljoin

import requests


MONEYCONTROL_SOURCES = (
    # Hindi markets is intentionally first because Moneycontrol often publishes
    # pre-open catalyst articles there before the English market article appears.
    "https://www.moneycontrol.com/news/business/markets/stocks-to-watch-today-nse-spectraa-technology-sonaselection-meesho-sedemac-mechatronics-welspun-living-bharat-dynamics-max-estates-in-focus-on-24-september-14036780.html",
    "https://hindi.moneycontrol.com/news/markets",
    "https://www.moneycontrol.com/news/tags/stocks-to-watch.html",
    "https://www.moneycontrol.com/news/tags/stocks-in-news.html",
    "https://www.moneycontrol.com/news/business/markets/",
    "https://www.moneycontrol.com/features/rss/news/business/companies/",
)

OTHER_MARKET_SOURCES = (
    "https://economictimes.indiatimes.com/markets/stocks/news",
    "https://www.business-standard.com/markets/news",
    "https://www.livemint.com/market",
    "https://www.cnbctv18.com/market/",
    "https://news.google.com/rss/search?q=Indian+stock+market+stocks+in+news+F%26O+India&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=Indian+corporate+announcements+stocks+India&hl=en-IN&gl=IN&ceid=IN:en",
)

POSITIVE_WORDS = (
    "order win", "order worth", "approval", "approved", "acquired", "acquisition",
    "contract", "jda", "joint development", "bonus", "funding", "investment",
    "stake buy", "buyout", "raises", "record order", "new order", "commissioned",
)
NEGATIVE_WORDS = (
    "crash", "plunge", "falls", "fall", "sell-off", "lower circuit", "downgrade",
    "stake sale", "sold stake", "regulatory", "penalty", "probe", "show cause",
    "cut", "cuts", "commission cap", "earnings risk", "fraud", "default",
)
MATERIAL_WORDS = (
    "results", "earnings", "guidance", "outlook", "management", "ceo", "cfo",
    "merger", "demerger", "rights issue", "block deal", "bulk deal", "promoter",
    "ipo", "listing", "dividend", "capacity", "expansion",
)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
            return
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip = max(0, self._skip - 1)
            return
        if tag == "a" and self._href:
            title = re.sub(r"\s+", " ", html.unescape(" ".join(self._parts))).strip()
            if title and len(title) >= 12:
                self.links.append((self._href, title))
            self._href = ""
            self._parts = []


@dataclass
class NewsItem:
    title: str
    url: str
    text: str
    impact: str
    published_at: str | None = None


def _norm(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _fetch(url: str) -> str:
    response = requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 Safari/605.1.15"
            ),
            "Accept-Language": "en-IN,en;q=0.9",
        },
        timeout=12,
    )
    response.raise_for_status()
    return response.text


def _impact(text: str) -> str:
    low = _norm(text)
    pos = sum(1 for word in POSITIVE_WORDS if _norm(word) in low)
    neg = sum(1 for word in NEGATIVE_WORDS if _norm(word) in low)
    mat = sum(1 for word in MATERIAL_WORDS if _norm(word) in low)
    if neg and neg >= pos:
        return "NEGATIVE CATALYST"
    if pos > neg:
        return "POSITIVE CATALYST"
    if mat:
        return "MATERIAL EVENT"
    return "NEWS"


def fetch_moneycontrol_news(max_items: int = 60) -> list[NewsItem]:
    """Fetch current Moneycontrol stock-watch/news headlines for the morning scan.

    The scanner treats Moneycontrol as a catalyst source, not as a trading signal.
    """
    seen: set[str] = set()
    items: list[NewsItem] = []

    for source in MONEYCONTROL_SOURCES + OTHER_MARKET_SOURCES:
        try:
            raw_html = _fetch(source)
            parser = _LinkParser()
            parser.feed(raw_html)

            # Direct article pages may not expose their own headline as an <a>
            # link, so also capture the HTML title and social/meta title.
            direct_titles: list[str] = []
            patterns = (
                r"<meta[^>]+(?:property|name)=[\"\'](?:og:title|twitter:title)[\"\'][^>]+content=[\"\']([^\"\']+)[\"\']",
                r'<title[^>]*>(.*?)</title>',
            )
            for pattern in patterns:
                for match in re.findall(pattern, raw_html, flags=re.IGNORECASE | re.DOTALL):
                    title = re.sub(r"\s+", " ", html.unescape(match)).strip()
                    if title:
                        direct_titles.append(title)

            for title in direct_titles:
                key = _norm(title)
                if key and key not in seen and len(key) >= 12:
                    seen.add(key)
                    items.append(
                        NewsItem(title=title[:300], url=source, text=title, impact=_impact(title))
                    )
                    if len(items) >= max_items:
                        return items

            for raw_url, title in parser.links:
                url = urljoin(source, raw_url)
                allowed_hosts = ("moneycontrol.com", "economictimes.indiatimes.com", "business-standard.com", "livemint.com", "cnbctv18.com", "news.google.com")
                if not any(host in url.lower() for host in allowed_hosts):
                    continue
                key = _norm(title)
                if key in seen:
                    continue
                seen.add(key)
                if not any(token in url for token in ("/news/", "/features/", "/market", "/markets", "news.google.com/rss/")):
                    continue
                impact = _impact(title)
                items.append(NewsItem(title=title, url=url, text=title, impact=impact))
                if len(items) >= max_items:
                    return items
        except Exception as exc:
            print(f"[NEWS WARNING] Moneycontrol source failed: {source}: {exc}")

    return items


def _aliases(symbol: str, company_name: str) -> list[str]:
    aliases = [_norm(symbol), _norm(company_name)]
    known_aliases = {
        "policybzr": ["pb fintech", "policybazaar", "policy bazaar"],
        "aubank": ["au small finance bank", "au bank"],
        "icicigi": ["icici lombard", "icici lombard general insurance"],
        "bajajfinsv": ["bajaj finserv"],
        "suzlon": ["suzlon energy"],
    }
    aliases.extend(_norm(x) for x in known_aliases.get(_norm(symbol), []))
    company = _norm(company_name)
    # Company names often contain legal suffixes that make exact matching noisy.
    company = re.sub(
        r"\b(limited|ltd|india|inc|corporation|corp|company|co|plc)\b",
        " ",
        company,
    )
    company = re.sub(r"\s+", " ", company).strip()
    if len(company) >= 6:
        aliases.append(company)
    return [x for x in dict.fromkeys(aliases) if len(x) >= 3]


def match_news(
    symbol: str,
    company_name: str,
    items: Iterable[NewsItem],
) -> tuple[int, str, list[dict[str, str]]]:
    aliases = _aliases(symbol, company_name)
    matched: list[NewsItem] = []

    for item in items:
        blob = _norm(item.title + " " + item.text)
        if any(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", blob) for alias in aliases):
            matched.append(item)

    if not matched:
        return 0, "NO MATERIAL NEWS", []

    score = min(30, 10 + (len(matched) - 1) * 5)
    impacts = {item.impact for item in matched}
    if "NEGATIVE CATALYST" in impacts or "POSITIVE CATALYST" in impacts:
        score = min(30, score + 5)
    if len(matched) >= 3:
        score = 30

    payload = [
        {"title": item.title[:240], "url": item.url, "impact": item.impact}
        for item in matched[:3]
    ]
    impact = "MATERIAL NEWS"
    if "NEGATIVE CATALYST" in impacts and "POSITIVE CATALYST" not in impacts:
        impact = "NEGATIVE CATALYST"
    elif "POSITIVE CATALYST" in impacts and "NEGATIVE CATALYST" not in impacts:
        impact = "POSITIVE CATALYST"

    return score, impact, payload
