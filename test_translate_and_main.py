from __future__ import annotations

from fetch_news import ArticleMetadata
from fetch_news import NewsItem
from main import enrich_item, select_balanced_items


def test_english_news_translates_and_keeps_fields_complete(monkeypatch):
    calls = {"translate": [], "summarize": []}

    def fake_translate(text, api_key, base_url, model="gpt-4.1-mini"):
        calls["translate"].append((text, api_key, model))
        return f"中文：{text}"

    def fake_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini"):
        calls["summarize"].append((title, description, api_key, model))
        return "中文摘要：这是一条新闻"

    monkeypatch.setattr("main.translate_to_zh_with_base_url", fake_translate)
    monkeypatch.setattr("main.summarize_to_zh", fake_summarize)

    item = NewsItem(
        title="OpenAI launches a new model",
        url="https://example.com/article",
        source="Google News AI",
        language="en",
        source_priority=1,
        image_url="",
        published_at="2026-06-02T08:00:00+08:00",
        published_date="2026-06-02",
        summary="The new model improves reasoning.",
        raw_title="OpenAI launches a new model",
        raw_summary="The new model improves reasoning.",
    )

    enriched = enrich_item(
        item,
        openai_api_key="test-key",
        openai_base_url="https://api.example.com/v1",
        openai_model="gpt-4.1-mini",
    )

    assert enriched["title"] == "中文：OpenAI launches a new model"
    assert enriched["url"] == item.url
    assert enriched["source"] == item.source
    assert enriched["published_at"] == item.published_at
    assert enriched["summary"].startswith("中文摘要：这是一条新闻")
    assert len(enriched["summary"]) >= 80
    assert enriched["original_title"] == item.raw_title
    assert len(calls["translate"]) == 1
    assert len(calls["summarize"]) == 1


def test_english_news_falls_back_when_openai_fails(monkeypatch):
    def failing_translate(text, api_key, base_url, model="gpt-4.1-mini"):
        raise RuntimeError("provider unavailable")

    def failing_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini"):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("main.translate_to_zh_with_base_url", failing_translate)
    monkeypatch.setattr("main.summarize_to_zh", failing_summarize)
    monkeypatch.setattr(
        "main.translate_to_zh_fallback",
            lambda text: {
                "OpenAI launches a new model": "OpenAI 发布新模型",
                "The new model improves reasoning. The launch gives developers stronger coding, analysis and planning capabilities.": (
                    "新模型提升了推理能力。此次发布为开发者带来更强的编码、分析和规划能力。"
                ),
        }.get(text, text),
    )

    item = NewsItem(
        title="OpenAI launches a new model",
        url="https://example.com/article",
        source="Google News AI",
        language="en",
        source_priority=1,
        image_url="",
        published_at="2026-06-02T08:00:00+08:00",
        published_date="2026-06-02",
        summary="The new model improves reasoning.",
        raw_title="OpenAI launches a new model",
        raw_summary="The new model improves reasoning.",
    )
    metadata = ArticleMetadata(
        title="OpenAI launches a new model",
        description="The new model improves reasoning.",
        text="The launch gives developers stronger coding, analysis and planning capabilities.",
    )

    enriched = enrich_item(
        item,
        openai_api_key="test-key",
        openai_base_url="https://api.example.com/v1",
        openai_model="gpt-4.1-mini",
        metadata=metadata,
    )

    assert enriched["title"] == "OpenAI 发布新模型"
    assert enriched["original_title"] == item.raw_title
    assert enriched["summary"].startswith("据 Google News AI 报道，")
    assert "新模型提升了推理能力" in enriched["summary"]
    assert enriched["url"] == item.url
    assert enriched["source"] == item.source
    assert enriched["published_at"] == item.published_at


def test_select_balanced_items_keeps_domestic_and_overseas_news():
    overseas = [
        NewsItem(
            title=f"AI global {index}",
            url=f"https://example.com/en/{index}",
            source="Google News AI Global",
            language="en",
            source_priority=100,
            image_url="",
            published_at="2026-06-02T08:00:00+08:00",
            published_date="2026-06-02",
            summary="Summary",
            raw_title=f"AI global {index}",
            raw_summary="Summary",
        )
        for index in range(12)
    ]
    domestic = [
        NewsItem(
            title=f"国内 AI {index}",
            url=f"https://example.com/zh/{index}",
            source="Google News 人工智能",
            language="zh",
            source_priority=70,
            image_url="",
            published_at="2026-06-02T08:00:00+08:00",
            published_date="2026-06-02",
            summary="摘要",
            raw_title=f"国内 AI {index}",
            raw_summary="摘要",
        )
        for index in range(5)
    ]

    selected = select_balanced_items(overseas + domestic, max_items=15)

    assert len(selected) == 15
    assert sum(item.language == "zh" for item in selected) >= 4
    assert sum(item.language == "en" for item in selected) >= 6
