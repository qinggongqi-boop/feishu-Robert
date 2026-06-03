from __future__ import annotations

from dedupe import filter_unsent, mark_sent
from fetch_news import NewsItem


def _item(url: str, title: str = "Title") -> NewsItem:
    return NewsItem(
        title=title,
        url=url,
        source="Test",
        language="zh",
        source_priority=0,
        image_url="",
        published_at="2026-06-02T08:00:00+08:00",
        published_date="2026-06-02",
        summary="Summary",
        raw_title=title,
        raw_summary="Summary",
    )


def test_duplicate_urls_do_not_get_returned_twice(tmp_path):
    db_path = tmp_path / "sent_urls.sqlite3"
    items = [
        _item("https://example.com/article?utm_source=news", "A"),
        _item("https://example.com/article?utm_medium=email", "B"),
    ]

    unsent = filter_unsent(db_path, items)
    assert len(unsent) == 1
    assert unsent[0].url.startswith("https://example.com/article")


def test_sent_url_is_not_returned_again_after_marking_sent(tmp_path):
    db_path = tmp_path / "sent_urls.sqlite3"
    item = _item("https://example.com/article?utm_source=news")

    mark_sent(db_path, item)
    unsent = filter_unsent(db_path, [item])

    assert unsent == []
