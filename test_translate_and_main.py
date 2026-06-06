from __future__ import annotations

from fetch_news import ArticleMetadata
from fetch_news import NewsItem
from main import (
    compact_editorial_summary,
    enrich_item,
    is_content_quality_ok,
    is_raw_item_quality_ok,
    looks_mojibake,
    review_chinese_translation,
    select_balanced_items,
)
from translate import translate_to_zh_stable


def test_english_news_translates_and_keeps_fields_complete(monkeypatch):
    calls = {"stable_translate": [], "openai_translate": [], "summarize": []}

    def fake_stable_translate(text, azure_key=None, azure_region=None, **kwargs):
        calls["stable_translate"].append((text, azure_key, azure_region, kwargs))
        if "reasoning, coding and planning" in text:
            return "OpenAI 发布的新模型提升了推理、编码和规划能力，面向开发者和企业生产场景。后续重点看它在真实业务中的稳定性和落地效果。"
        return "OpenAI 发布新的 AI 模型"

    def fake_openai_translate(text, api_key, base_url, model="gpt-4.1-mini"):
        calls["openai_translate"].append((text, api_key, model))
        return f"OpenAI 中文：{text}"

    def fake_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini"):
        calls["summarize"].append((title, description, api_key, model))
        return "OpenAI 发布的新模型提升了推理、编码和规划能力，面向开发者和企业生产场景。后续重点看它在真实业务中的稳定性和落地效果。"

    monkeypatch.setattr("main.translate_to_zh_stable", fake_stable_translate)
    monkeypatch.setattr("main.translate_to_zh_with_base_url", fake_openai_translate)
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
        summary=(
            "The new model improves reasoning, coding and planning for developers. "
            "OpenAI says the release is aimed at production use cases and enterprise teams."
        ),
        raw_title="OpenAI launches a new model",
        raw_summary=(
            "The new model improves reasoning, coding and planning for developers. "
            "OpenAI says the release is aimed at production use cases and enterprise teams."
        ),
    )

    enriched = enrich_item(
        item,
        openai_api_key="test-key",
        openai_base_url="https://api.example.com/v1",
        openai_model="gpt-4.1-mini",
        azure_translator_key="azure-key",
        azure_translator_region="eastasia",
    )

    assert enriched["title"] == "OpenAI 发布新的 AI 模型"
    assert enriched["url"] == item.url
    assert enriched["source"] == item.source
    assert enriched["published_at"] == item.published_at
    assert enriched["summary"].startswith("OpenAI 发布的新模型提升了推理")
    assert len(enriched["summary"]) <= 190
    assert enriched["original_title"] == item.raw_title
    assert calls["stable_translate"][0] == (
        "OpenAI launches a new model",
        "azure-key",
        "eastasia",
        {
            "volcengine_access_key_id": None,
            "volcengine_secret_access_key": None,
            "volcengine_region": "cn-north-1",
        },
    )
    assert calls["openai_translate"] == []
    assert calls["summarize"] == []


def test_english_news_falls_back_when_openai_fails(monkeypatch):
    def failing_translate(text, api_key, base_url, model="gpt-4.1-mini"):
        raise RuntimeError("provider unavailable")

    def failing_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini"):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("main.translate_to_zh_with_base_url", failing_translate)
    monkeypatch.setattr("main.summarize_to_zh", failing_summarize)
    def fake_stable_translate(text, azure_key=None, azure_region=None, **kwargs):
        if text == "OpenAI launches a new model":
            return "OpenAI 发布新模型"
        if "The new model improves reasoning" in text:
            return "新模型提升了推理能力。此次发布为开发者带来更强的编码、分析和规划能力。"
        return text

    monkeypatch.setattr("main.translate_to_zh_stable", fake_stable_translate)

    item = NewsItem(
        title="OpenAI launches a new model",
        url="https://example.com/article",
        source="Google News AI",
        language="en",
        source_priority=1,
        image_url="",
        published_at="2026-06-02T08:00:00+08:00",
        published_date="2026-06-02",
        summary="The new model improves reasoning. The launch gives developers stronger coding, analysis and planning capabilities.",
        raw_title="OpenAI launches a new model",
        raw_summary="The new model improves reasoning. The launch gives developers stronger coding, analysis and planning capabilities.",
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
        azure_translator_key="azure-key",
        azure_translator_region="eastasia",
    )

    assert enriched["title"] == "OpenAI 发布新模型"
    assert enriched["original_title"] == item.raw_title
    assert "新模型提升了推理能力" in enriched["summary"]
    assert enriched["url"] == item.url
    assert enriched["source"] == item.source
    assert enriched["published_at"] == item.published_at


def test_noise_source_and_summary_are_rejected():
    noisy = NewsItem(
        title="Oracle faces questions around pace of AI data center buildout",
        url="https://www.moomoo.com/hans/news/post/example",
        source="Moomoo",
        language="zh",
        source_priority=1,
        image_url="",
        published_at="2026-06-02T08:00:00+08:00",
        published_date="2026-06-02",
        summary="甲骨文数据中心建设受到关注。はじめての方へ 口座開設の流れ 入金 出金 米国株現物取引",
        raw_title="Oracle faces questions around pace of AI data center buildout",
        raw_summary="甲骨文数据中心建设受到关注。はじめての方へ 口座開設の流れ 入金 出金 米国株現物取引",
    )

    assert not is_raw_item_quality_ok(noisy)
    assert not is_content_quality_ok("甲骨文数据中心建设受到关注", noisy.summary, noisy.raw_title)


def test_compact_editorial_summary_removes_noise_and_keeps_key_points():
    summary = compact_editorial_summary(
        "谷歌回顾 5 月份推出的人工智能产品，涵盖 Gemini、Android、量子计算和健康领域。"
        "《每日报》将最新技术更新直接发送到您的收件箱。"
        "这些更新显示，Google 正把 AI 能力继续嵌入云、移动端和科研产品。"
        "后续值得关注这些功能能否进入企业客户和消费端应用。"
    )

    assert "每日报" not in summary
    assert "Gemini" in summary
    assert len(summary) <= 190


def test_translate_to_zh_stable_uses_volcengine_first(monkeypatch):
    calls = []

    def fake_volcengine(text, access_key_id, secret_access_key, region):
        calls.append(("volcengine", text, access_key_id, secret_access_key, region))
        return "火山中文标题"

    def fake_azure(text, key, region):
        calls.append(("azure", text, key, region))
        return "Azure 中文标题"

    def fake_google(text):
        calls.append(("google", text))
        return "Google 中文标题"

    monkeypatch.setattr("translate.translate_to_zh_volcengine", fake_volcengine)
    monkeypatch.setattr("translate.translate_to_zh_azure", fake_azure)
    monkeypatch.setattr("translate.translate_to_zh_fallback", fake_google)

    translated = translate_to_zh_stable(
        "OpenAI launches a new model",
        azure_key="azure-key",
        azure_region="eastasia",
        volcengine_access_key_id="ak",
        volcengine_secret_access_key="sk",
        volcengine_region="cn-north-1",
    )

    assert translated == "火山中文标题"
    assert calls == [("volcengine", "OpenAI launches a new model", "ak", "sk", "cn-north-1")]


def test_translate_to_zh_stable_falls_back_to_azure_when_volcengine_returns_source(monkeypatch):
    calls = []

    def fake_volcengine(text, access_key_id, secret_access_key, region):
        calls.append(("volcengine", text, access_key_id, secret_access_key, region))
        return text

    def fake_azure(text, key, region):
        calls.append(("azure", text, key, region))
        return "Azure 中文标题"

    def fake_google(text):
        calls.append(("google", text))
        return "Google 中文标题"

    monkeypatch.setattr("translate.translate_to_zh_volcengine", fake_volcengine)
    monkeypatch.setattr("translate.translate_to_zh_azure", fake_azure)
    monkeypatch.setattr("translate.translate_to_zh_fallback", fake_google)

    translated = translate_to_zh_stable(
        "OpenAI launches a new model",
        azure_key="azure-key",
        azure_region="eastasia",
        volcengine_access_key_id="ak",
        volcengine_secret_access_key="sk",
        volcengine_region="cn-north-1",
    )

    assert translated == "Azure 中文标题"
    assert calls == [
        ("volcengine", "OpenAI launches a new model", "ak", "sk", "cn-north-1"),
        ("azure", "OpenAI launches a new model", "azure-key", "eastasia"),
    ]


def test_review_chinese_translation_fixes_son_context():
    reviewed = review_chinese_translation(
        "AI 正在设计 OpenAI 的模型：儿子修改了 ASI 时间表",
        "AI Is Designing OpenAI's Models: Masayoshi Son Revises His ASI Timeline",
    )

    assert "孙正义" in reviewed
    assert "儿子" not in reviewed


def test_quality_gate_rejects_mojibake_english_and_short_summary():
    assert looks_mojibake("Ã¥ÂÂ«Ã¦ÂœÂ‰Ã¤Â¹Â±Ã§Â ÂÃ§ÂšÂ„Ã¦Â–Â‡Ã¦ÂœÂ¬")
    assert not is_content_quality_ok(
        "OpenAI launches a new model",
        "这是一段长度足够的中文摘要，介绍新闻背景、事件经过、行业影响和后续值得关注的问题。"
        "这是一段长度足够的中文摘要，介绍新闻背景、事件经过、行业影响和后续值得关注的问题。",
        "OpenAI launches a new model",
    )
    assert not is_content_quality_ok(
        "OpenAI 发布新模型",
        "太短",
        "OpenAI launches a new model",
    )
    assert is_content_quality_ok(
        "OpenAI 发布新模型",
        "这是一段长度足够的中文摘要，介绍新闻背景、事件经过、行业影响和后续值得关注的问题。"
        "它会进一步影响开发者工具、企业应用和模型竞争格局，也需要继续观察产品稳定性与商业化落地。"
        "从行业角度看，这类发布通常会改变企业采购、开发者生态和竞争对手的产品节奏。",
        "OpenAI launches a new model",
    )


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
