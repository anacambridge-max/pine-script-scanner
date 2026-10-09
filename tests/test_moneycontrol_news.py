from worker import moneycontrol_news


def test_rss_title_pubdate_and_description_are_parsed(monkeypatch):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><item>
      <title>HAL wins a major order</title>
      <link>https://example.com/hal-order</link>
      <pubDate>Thu, 08 Oct 2026 03:00:00 GMT</pubDate>
      <description><![CDATA[HAL receives a large defence contract.]]></description>
    </item></channel></rss>"""
    monkeypatch.setattr(moneycontrol_news, "MONEYCONTROL_SOURCES", ("https://example.com/rss.xml",))
    monkeypatch.setattr(moneycontrol_news, "OTHER_MARKET_SOURCES", ())
    monkeypatch.setattr(moneycontrol_news, "_fetch", lambda _url: xml)

    items = moneycontrol_news.fetch_moneycontrol_news(max_items=1)
    assert len(items) == 1
    assert items[0].title == "HAL wins a major order"
    assert items[0].published_at == "Thu, 08 Oct 2026 03:00:00 GMT"
    assert "large defence contract" in items[0].text
    assert items[0].url == "https://example.com/hal-order"
