from __future__ import annotations

from fetch_news import NewsItem
from main import enrich_item


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
    assert enriched["summary"] == "中文摘要：这是一条新闻"
    assert len(calls["translate"]) == 2
    assert len(calls["summarize"]) == 1


def test_english_news_falls_back_when_openai_fails(monkeypatch):
    def failing_translate(text, api_key, base_url, model="gpt-4.1-mini"):
        raise RuntimeError("provider unavailable")

    def failing_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini"):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("main.translate_to_zh_with_base_url", failing_translate)
    monkeypatch.setattr("main.summarize_to_zh", failing_summarize)

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

    assert enriched["title"] == f"海外 AI 新闻：{item.title}"
    assert enriched["summary"].startswith("这是一条来自 Google News AI 的海外 AI 新闻。原文要点：")
    assert enriched["url"] == item.url
    assert enriched["source"] == item.source
    assert enriched["published_at"] == item.published_at
