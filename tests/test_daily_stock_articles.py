from datetime import datetime
from zoneinfo import ZoneInfo

from worker import daily_stock_articles as articles


def test_same_day_publisher_mentions_and_moneycontrol_results(monkeypatch):
    upstox_index = "https://upstox.com/news/market-news/stocks/"
    moneycontrol_index = "https://www.moneycontrol.com/news/business/markets/"
    upstox_article = "https://upstox.com/news/market-news/stocks/stocks-to-watch-today/article-1/"
    moneycontrol_article = "https://www.moneycontrol.com/news/business/markets/stocks-to-watch-today-1.html"
    old_article = "https://www.moneycontrol.com/news/business/markets/stocks-to-watch-yesterday-1.html"
    pages = {
        upstox_index: f'<a href="{upstox_article}">Stocks to watch today</a>',
        moneycontrol_index: (f'<a href="{moneycontrol_article}">Stocks to watch today</a>'
                             f'<a href="{old_article}">Stocks to watch yesterday</a>'),
        upstox_article: ('<meta property="article:published_time" content="2026-11-03T08:05:00+05:30">'
                         '<h1>Stocks to watch today</h1><p>Delhivery is in focus today.</p>'),
        moneycontrol_article: ('<meta property="article:published_time" content="2026-11-03T07:15:00+05:30">'
                               '<h1>Stocks to watch today</h1><p>Dixon Technologies will release quarterly results today.</p>'),
        old_article: ('<meta property="article:published_time" content="2026-11-02T07:15:00+05:30">'
                      '<h1>Stocks to watch yesterday</h1><p>Delhivery is in focus.</p>'),
    }
    monkeypatch.setattr(articles, "INDEX_PAGES", (upstox_index, moneycontrol_index))
    monkeypatch.setattr(articles, "_fetch", pages.__getitem__)
    instruments = [
        {"trading_symbol": "DELHIVERY", "company_name": "Delhivery Limited"},
        {"trading_symbol": "DIXON", "company_name": "Dixon Technologies Limited"},
    ]
    now = datetime(2026, 11, 3, 9, 20, tzinfo=ZoneInfo("Asia/Kolkata"))

    found = articles.fetch_daily_stock_articles(instruments, now)

    assert len(found["DELHIVERY"]) == 1
    assert found["DELHIVERY"][0]["source"] == "Upstox"
    assert found["DIXON"][0]["kind"] == "EARNINGS / RESULTS"
    assert all(item["published_at"].startswith("2026-11-03") for rows in found.values() for item in rows)
    assert all("NOT A TRADE SIGNAL" in item["impact"] for rows in found.values() for item in rows)


def test_upstox_jsonld_date_and_article_body_when_moneycontrol_is_blocked(monkeypatch):
    import json

    index = "https://upstox.com/news/market-news/stocks/"
    article = "https://upstox.com/news/market-news/stocks/stocks-to-watch-nov-3/article-2/"
    blocked = "https://www.moneycontrol.com/news/business/markets/"
    body = "Lupin: Earnings are due today.\n\nITC: Quarterly revenue rose."
    structured = {"@type": "NewsArticle", "headline": "Stocks to watch, Nov 3: Lupin, ITC",
                  "datePublished": "2026-11-03T08:13:32+05:30", "articleBody": body}
    pages = {index: f'<a href="{article}">Stocks to watch, Nov 3: Lupin, ITC</a>',
             article: f'<script type="application/ld+json">{json.dumps(structured)}</script>'}

    def fetch(url):
        if url == blocked:
            raise PermissionError("403 Forbidden")
        return pages[url]

    monkeypatch.setattr(articles, "INDEX_PAGES", (index, blocked))
    monkeypatch.setattr(articles, "_fetch", fetch)
    found = articles.fetch_daily_stock_articles(
        [{"trading_symbol": "LUPIN", "company_name": "Lupin Limited"},
         {"trading_symbol": "ITC", "company_name": "ITC Limited"}],
        datetime(2026, 11, 3, 9, 20, tzinfo=ZoneInfo("Asia/Kolkata")),
    )

    assert set(found) == {"LUPIN", "ITC"}
    assert found["LUPIN"][0]["context"] == "Lupin: Earnings are due today."
    assert found["ITC"][0]["context"] == "ITC: Quarterly revenue rose."


def test_moneycontrol_article_body_excludes_unrelated_sidebar(monkeypatch):
    import json

    index = "https://www.moneycontrol.com/news/business/markets/"
    article = "https://www.moneycontrol.com/news/business/markets/stocks-to-watch-today.html"
    structured = {"@type": "NewsArticle", "headline": "Stocks to watch today",
                  "datePublished": "2026-11-03T06:36:14+05:30",
                  "articleBody": "ITC Q2 results\r \rProfit fell today.\r \rRevenue surged.\r \rMarico Q2 results\r \rProfit rose today.\r \rNBCC Q2: won a contract from Hindustan Aeronautics."}
    raw_json = json.dumps([structured]).replace("\\r", "\r")
    pages = {index: f'<a href="{article}">Stocks to watch today</a>',
             article: f'<script type="application/ld+json">{raw_json}</script><p>HAL stock rises elsewhere</p>'}
    monkeypatch.setattr(articles, "INDEX_PAGES", (index,))
    monkeypatch.setattr(articles, "_fetch", pages.__getitem__)
    found = articles.fetch_daily_stock_articles(
        [{"trading_symbol": symbol, "company_name": "Hindustan Aeronautics" if symbol == "HAL" else symbol}
         for symbol in ("ITC", "MARICO", "HAL")],
        datetime(2026, 11, 3, 9, 20, tzinfo=ZoneInfo("Asia/Kolkata")),
    )

    assert set(found) == {"ITC", "MARICO"}
    assert found["ITC"][0]["context"] == "ITC Q2 results Profit fell today. Revenue surged."
    assert found["MARICO"][0]["context"] == "Marico Q2 results Profit rose today."
