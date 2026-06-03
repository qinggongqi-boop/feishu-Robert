from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import fetch_news
from config import SourceConfig


class _FakeFeed:
    def __init__(self, entries):
        self.entries = entries


def test_yesterday_news_is_recognized_after_timezone_conversion(monkeypatch):
    tz_name = "Asia/Shanghai"
    target_date = "2026-06-02"
    entry = {
        "title": "AI news",
        "link": "https://example.com/article?utm_source=news",
        "summary": "Summary",
        "published": "Mon, 01 Jun 2026 16:30:00 GMT",
    }

    monkeypatch.setattr(fetch_news, "_fetch_feed_bytes", lambda *args, **kwargs: b"<rss></rss>")
    monkeypatch.setattr(fetch_news.feedparser, "parse", lambda data: _FakeFeed([entry]))
    source = SourceConfig(
        name="Test RSS",
        kind="rss",
        language="en",
        url="https://example.com/rss",
        priority=0,
    )

    items = fetch_news.fetch_source_news(source, tz_name)
    assert len(items) == 1
    assert items[0].published_date == target_date
    assert items[0].image_url == ""

    filtered = fetch_news.filter_items_by_date(items, target_date)
    assert [item.title for item in filtered] == ["AI news"]
    assert filtered[0].published_at.startswith("2026-06-02T00:30:00")
