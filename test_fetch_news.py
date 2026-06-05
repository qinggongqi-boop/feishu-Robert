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


def test_google_news_placeholder_image_is_detected():
    assert fetch_news.is_google_news_placeholder_image(
        "https://lh3.googleusercontent.com/J6_coFbogxhRI9iM864NL_liGXvsQp2AupsKei7z0cNNfDvGUmWUy20nuUhkREQyrpY4bEeIBuc=s0-w300"
    )
    assert not fetch_news.is_google_news_placeholder_image("https://example.com/news-cover.jpg")


def test_resolve_google_news_url_uses_batchexecute(monkeypatch):
    google_url = "https://news.google.com/rss/articles/CBMiExample?oc=5"

    def fake_fetch_html(url, timeout_seconds, retries, user_agent):
        assert url == google_url
        return (
            '<div data-n-a-id="CBMiExample" '
            'data-n-a-ts="1780682870" '
            'data-n-a-sg="signature"></div>'
        )

    class FakeResponse:
        text = ')]}\'\n[["wrb.fr","Fbv4je","[\\"garturlres\\",\\"https://example.com/story?utm_source=google\\",1]"]]'

        def raise_for_status(self):
            return None

    def fake_post(url, headers, data, timeout):
        assert "batchexecute" in url
        assert "f.req" in data
        return FakeResponse()

    monkeypatch.setattr(fetch_news, "_fetch_html", fake_fetch_html)
    monkeypatch.setattr(fetch_news.requests, "post", fake_post)

    assert fetch_news.resolve_google_news_url(google_url, 15, 1, "UA") == "https://example.com/story"
