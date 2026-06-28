from __future__ import annotations

from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo

import pytest

import daily_brief
from daily_brief import BriefArticle, BriefConfig, FeedSource


def make_config(**overrides) -> BriefConfig:
    values = {
        "feeds_path": overrides.pop("feeds_path", "feeds.json"),
        "lookback_hours": 30,
        "max_articles_per_topic": 10,
        "timezone_name": "Asia/Shanghai",
        "openai_api_key": "sk-test",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_model": "gpt-4.1-mini",
        "feishu_webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/test",
        "feishu_secret": None,
        "text_only": False,
        "timeout_seconds": 15,
        "retries": 1,
        "user_agent": "pytest",
    }
    values.update(overrides)
    return BriefConfig(**values)


def make_article(
    title: str,
    *,
    topic: str = "AI / 模型 / Codex / Agent",
    url: str = "https://example.com/a",
    published_at: datetime | None = None,
) -> BriefArticle:
    return BriefArticle(
        topic=topic,
        source="Example",
        title=title,
        url=url,
        summary="Short summary",
        published_at=published_at,
    )


def test_load_feeds_reads_json_array(tmp_path):
    feeds_path = tmp_path / "feeds.json"
    feeds_path.write_text(
        json.dumps(
            [
                {
                    "topic": "AI / 模型 / Codex / Agent",
                    "source": "OpenAI News",
                    "url": "https://openai.com/news/rss.xml",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    feeds = daily_brief.load_feeds(feeds_path)

    assert feeds == [
        FeedSource(
            topic="AI / 模型 / Codex / Agent",
            source="OpenAI News",
            url="https://openai.com/news/rss.xml",
        )
    ]


def test_load_feeds_rejects_invalid_json_shape(tmp_path):
    feeds_path = tmp_path / "feeds.json"
    feeds_path.write_text('{"topic": "bad"}', encoding="utf-8")

    with pytest.raises(daily_brief.BriefConfigError, match="JSON array"):
        daily_brief.load_feeds(feeds_path)


def test_filter_by_lookback_keeps_recent_and_unknown_time_but_drops_old():
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 6, 28, 9, 0, tzinfo=tz)
    recent = make_article("recent", url="https://example.com/recent", published_at=now - timedelta(hours=2))
    unknown = make_article("unknown", url="https://example.com/unknown", published_at=None)
    old = make_article("old", url="https://example.com/old", published_at=now - timedelta(hours=48))

    kept = daily_brief.filter_by_lookback(
        [recent, unknown, old],
        lookback_hours=30,
        now=now,
        timezone_name="Asia/Shanghai",
    )

    assert [item.title for item in kept] == ["recent", "unknown"]


def test_dedupe_articles_uses_url_and_title():
    articles = [
        make_article("Same title", url="https://example.com/a?utm_source=x"),
        make_article("Same title", url="https://example.com/b"),
        make_article("Different", url="https://example.com/a"),
        make_article("Different 2", url="https://example.com/c"),
    ]

    deduped = daily_brief.dedupe_articles(articles)

    assert [item.title for item in deduped] == ["Same title", "Different 2"]
    assert deduped[0].url == "https://example.com/a"


def test_limit_articles_per_topic_caps_each_topic():
    tz = ZoneInfo("Asia/Shanghai")
    articles = [
        make_article(f"ai-{index}", url=f"https://example.com/ai-{index}", published_at=datetime(2026, 6, 28, index, tzinfo=tz))
        for index in range(3)
    ]
    articles += [
        make_article(
            f"ads-{index}",
            topic="跨境电商 / Meta广告 / 爆款素材",
            url=f"https://example.com/ads-{index}",
            published_at=datetime(2026, 6, 28, index, tzinfo=tz),
        )
        for index in range(3)
    ]

    selected = daily_brief.limit_articles_per_topic(articles, max_per_topic=2)

    assert sum(item.topic == "AI / 模型 / Codex / Agent" for item in selected) == 2
    assert sum(item.topic == "跨境电商 / Meta广告 / 爆款素材" for item in selected) == 2


def test_feishu_sign_is_deterministic():
    timestamp, sign = daily_brief.feishu_sign("secret", timestamp=1234567890)

    assert timestamp == "1234567890"
    assert sign == "ZfKVuj6L5hFYWbpNk/R//8s1lu9nDXiIbG0Fc4NaCEk="


def test_build_brief_post_payload_matches_feishu_post_structure():
    articles = daily_brief.assign_reference_ids(
        [
            make_article("Title 1", url="https://example.com/1"),
            make_article("Title 2", url="https://example.com/2"),
        ]
    )

    payload = daily_brief.build_brief_post_payload("每日增长情报简报｜2026-06-28\n\n一、结论", articles, "2026-06-28")

    assert payload["msg_type"] == "post"
    assert payload["content"]["post"]["zh_cn"]["title"] == "每日增长情报简报｜2026-06-28"
    json_text = json.dumps(payload, ensure_ascii=False)
    assert "参考来源" in json_text
    assert '"href": "https://example.com/1"' in json_text
    assert "[S1]" in json_text


def test_send_brief_falls_back_to_text_when_post_fails(monkeypatch):
    calls: list[dict] = []

    def fake_send(webhook_url: str, payload: dict) -> str:
        calls.append(payload)
        if payload["msg_type"] == "post":
            raise RuntimeError("post failed")
        return '{"code":0}'

    monkeypatch.setattr(daily_brief, "send_feishu_webhook", fake_send)
    config = make_config()
    articles = daily_brief.assign_reference_ids([make_article("Title")])

    response = daily_brief.send_brief_to_feishu(config, "简报正文", articles, "2026-06-28")

    assert response == '{"code":0}'
    assert [payload["msg_type"] for payload in calls] == ["post", "text"]


def test_run_test_does_not_fetch_or_call_llm(monkeypatch):
    monkeypatch.setattr(daily_brief, "fetch_and_filter", lambda *args, **kwargs: pytest.fail("should not fetch"))
    monkeypatch.setattr(daily_brief, "generate_brief_text", lambda *args, **kwargs: pytest.fail("should not call llm"))
    monkeypatch.setattr(daily_brief, "send_feishu_webhook", lambda webhook_url, payload: '{"code":0}')

    assert daily_brief.run_test(make_config(openai_api_key=None)) == 0


def test_validate_config_requires_webhook():
    with pytest.raises(daily_brief.BriefConfigError, match="FEISHU_WEBHOOK"):
        daily_brief.validate_config(make_config(feishu_webhook=None), test_mode=True)
