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
