from __future__ import annotations

from feishu import build_feishu_payload, build_feishu_text_digest_payload, build_feishu_text_payload, payload_to_json


def test_feishu_payload_matches_webhook_structure():
    items = [
        {
            "title": "中文标题",
            "url": "https://example.com/article",
            "source": "Google News AI",
            "published_at": "2026-06-02T08:00:00+08:00",
            "summary": "中文摘要",
            "tag": "海外",
            "conclusion": "模型能力有明显提升",
            "image_url": "https://example.com/image.jpg",
            "cover": "https://example.com/image.jpg",
        }
    ]

    payload = build_feishu_payload(
        items,
        title="昨日 AI 新闻简报｜2026-06-02",
        total_count=10,
        selected_count=1,
        message_format="post",
    )
    json_text = payload_to_json(payload)

    assert payload["msg_type"] == "post"
    assert payload["content"]["post"]["zh_cn"]["title"] == "昨日 AI 新闻简报｜2026-06-02"
    assert isinstance(payload["content"]["post"]["zh_cn"]["content"], list)
    assert payload["content"]["post"]["zh_cn"]["content"][0][0]["text"].endswith("｜共抓取 10 条新闻，精选 1 条")
    assert "AI news 今日" in payload["content"]["post"]["zh_cn"]["content"][0][0]["text"]
    assert "中文标题" in json_text
    assert "https://example.com/article" in json_text
    assert "一句话结论" in json_text
    assert "中文摘要" in json_text
    assert "来源" in json_text
    assert "原文链接" in json_text
    assert "配图" in json_text


def test_feishu_card_payload_includes_card_elements():
    items = [
        {
            "title": "中文标题",
            "url": "https://example.com/article",
            "source": "Google News AI",
            "published_at": "2026-06-02T08:00:00+08:00",
            "summary": "中文摘要",
            "tag": "海外",
            "conclusion": "模型能力有明显提升",
            "image_key": "img_v3_testkey",
            "cover": "https://example.com/image.jpg",
        }
    ]

    payload = build_feishu_payload(
        items,
        title="昨日 AI 新闻简报｜2026-06-02",
        total_count=10,
        selected_count=1,
        message_format="card",
    )

    assert payload["msg_type"] == "interactive"
    assert payload["card"]["header"]["title"]["content"] == "昨日 AI 新闻简报｜2026-06-02"
    assert payload["card"]["config"]["wide_screen_mode"] is True
    assert payload["card"]["schema"] == "2.0"
    assert payload["card"]["body"]["elements"][0]["tag"] == "div"
    assert payload["card"]["body"]["elements"][2]["tag"] == "img"
    assert payload["card"]["body"]["elements"][2]["img_key"] == "img_v3_testkey"
    assert payload["card"]["body"]["elements"][3]["tag"] == "markdown"


def test_feishu_text_payload_matches_webhook_format():
    payload = build_feishu_text_payload("hello")

    assert payload == {
        "msg_type": "text",
        "content": {
            "text": "hello",
        },
    }


def test_feishu_payload_includes_custom_keyword():
    payload = build_feishu_payload(
        [],
        title="昨日 AI 新闻简报｜2026-06-02",
        total_count=10,
        selected_count=0,
        message_format="post",
        keyword="自定义关键词",
    )

    assert payload["content"]["post"]["zh_cn"]["content"][0][0]["text"] == "自定义关键词｜共抓取 10 条新闻，精选 0 条"


def test_feishu_text_digest_payload_includes_keyword_and_links():
    payload = build_feishu_text_digest_payload(
        [
            {
                "title": "中文标题",
                "url": "https://example.com/article",
                "source": "Google News AI",
                "summary": "中文摘要",
                "tag": "海外",
                "conclusion": "模型能力有明显提升",
            }
        ],
        title="昨日 AI 新闻简报｜2026-06-02",
        keyword="AI news 今日",
    )

    text = payload["content"]["text"]
    assert payload["msg_type"] == "text"
    assert text.startswith("AI news 今日｜昨日 AI 新闻简报｜2026-06-02")
    assert "https://example.com/article" in text
    assert "中文标题" in text
