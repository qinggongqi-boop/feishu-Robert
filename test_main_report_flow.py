from __future__ import annotations

import json

from dedupe import has_sent
from fetch_news import NewsItem
from main import build_report_notification_text, notify_from_meta, report_marker_url, write_report_meta


def _item(url: str) -> NewsItem:
    return NewsItem(
        title="Original title",
        url=url,
        source="Google News AI Global",
        language="en",
        source_priority=100,
        image_url="https://example.com/image.jpg",
        published_at="2026-06-05T08:00:00+08:00",
        published_date="2026-06-05",
        summary="Summary",
        raw_title="Original title",
        raw_summary="Summary",
    )


def test_report_notification_text_matches_feishu_copy():
    text = build_report_notification_text("https://example.com/2026-06-05.html", 15)

    assert text == "昨日 AI 科技新闻已更新，共 15 条，请查阅：\nhttps://example.com/2026-06-05.html"


def test_write_report_meta_and_notify_marks_urls_sent(tmp_path, monkeypatch):
    meta_path = write_report_meta(
        tmp_path / "report_meta.json",
        target_date="2026-06-05",
        report_url="https://example.com/2026-06-05.html",
        selected_count=1,
        total_count=20,
        items=[_item("https://example.com/article?utm_source=rss")],
    )
    sent_payloads = []

    def fake_send(webhook_url, payload):
        sent_payloads.append((webhook_url, payload))
        return '{"code":0}'

    monkeypatch.setattr("main.send_feishu_webhook", fake_send)

    payload = notify_from_meta(
        meta_path,
        db_path=tmp_path / "sent.sqlite3",
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        send=True,
    )

    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["selected_count"] == 1
    assert payload["msg_type"] == "text"
    assert "https://example.com/2026-06-05.html" in payload["content"]["text"]
    assert sent_payloads[0][0].startswith("https://open.feishu.cn")
    assert has_sent(tmp_path / "sent.sqlite3", "https://example.com/article")
    assert has_sent(tmp_path / "sent.sqlite3", report_marker_url("2026-06-05"))


def test_notify_from_meta_skips_duplicate_report_notification(tmp_path, monkeypatch):
    meta_path = write_report_meta(
        tmp_path / "report_meta.json",
        target_date="2026-06-05",
        report_url="https://example.com/2026-06-05.html",
        selected_count=1,
        total_count=20,
        items=[_item("https://example.com/article")],
    )
    sent_payloads = []

    def fake_send(webhook_url, payload):
        sent_payloads.append((webhook_url, payload))
        return '{"code":0}'

    monkeypatch.setattr("main.send_feishu_webhook", fake_send)
    db_path = tmp_path / "sent.sqlite3"

    notify_from_meta(
        meta_path,
        db_path=db_path,
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        send=True,
    )
    notify_from_meta(
        meta_path,
        db_path=db_path,
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/test",
        send=True,
    )

    assert len(sent_payloads) == 1
