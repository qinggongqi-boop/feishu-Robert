from __future__ import annotations

from fetch_news import ArticleMetadata
from fetch_news import NewsItem
from main import (
    compact_editorial_summary,
    enrich_item,
    enhance_final_summaries_with_model,
    is_content_quality_ok,
    is_raw_item_quality_ok,
    looks_mojibake,
    postprocess_chinese_text,
    review_chinese_translation,
    select_balanced_items,
)
from translate import translate_to_zh_stable
from translate import _openai_chat_url_candidates


def test_english_news_translates_and_keeps_fields_complete(monkeypatch):
    calls = {"stable_translate": [], "openai_translate": [], "summarize": []}

    def fake_stable_translate(text, azure_key=None, azure_region=None, **kwargs):
        calls["stable_translate"].append((text, azure_key, azure_region, kwargs))
        if "reasoning, coding and planning" in text:
            return (
                "OpenAI 发布的新模型提升了推理、编码和规划能力，面向开发者和企业生产场景。"
                "这意味着团队可以把模型用于代码生成、数据分析和复杂任务拆解，而不是只做简单问答。"
                "后续重点看它在真实业务中的稳定性、成本和落地效果。"
            )
        return "OpenAI 发布新的 AI 模型"

    def fake_openai_translate(text, api_key, base_url, model="gpt-4.1-mini"):
        calls["openai_translate"].append((text, api_key, model))
        return f"OpenAI 中文：{text}"

    def fake_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini", retries=1):
        calls["summarize"].append((title, description, api_key, model))
        return (
            "OpenAI 发布的新模型提升了推理、编码和规划能力，面向开发者和企业生产场景。"
            "这意味着团队可以把模型用于代码生成、数据分析和复杂任务拆解，而不是只做简单问答。"
            "后续重点看它在真实业务中的稳定性、成本和落地效果。"
        )

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
    assert 80 <= len(enriched["summary"]) <= 500
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


def test_model_summary_is_used_when_quality_gate_passes(monkeypatch):
    def fake_stable_translate(text, azure_key=None, azure_region=None, **kwargs):
        if text == "OpenAI launches a new model":
            return "OpenAI 发布新模型"
        return (
            "OpenAI 发布的新模型提升了推理、编码和规划能力，面向开发者和企业生产场景。"
            "这意味着团队可以把模型用于代码生成、数据分析和复杂任务拆解。"
        )

    def fake_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini", retries=1):
        return (
            "OpenAI 发布新的推理模型，重点提升代码、数学和规划任务的稳定性，并通过 API 面向开发者和企业客户开放。"
            "这会影响团队构建客服自动化、数据分析和内部知识库等 AI 应用的方式，也会加快同类模型在性能、价格和安全策略上的竞争。"
            "后续需要观察实际延迟、成本和企业落地效果。"
        )

    monkeypatch.setattr("main.translate_to_zh_stable", fake_stable_translate)
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
        summary="The new model improves reasoning, coding and planning for developers and enterprise teams.",
        raw_title="OpenAI launches a new model",
        raw_summary="The new model improves reasoning, coding and planning for developers and enterprise teams.",
    )

    enriched = enrich_item(
        item,
        openai_api_key="test-key",
        openai_base_url="https://api.example.com/v1",
        openai_model="gpt5.4-mini",
        metadata=ArticleMetadata(
            title="OpenAI launches a new model",
            description="The new model improves reasoning, coding and planning for developers and enterprise teams.",
            text=(
                "OpenAI says the release is designed for production use cases, including code generation, "
                "data analysis, customer support automation and internal knowledge base tools."
            ),
        ),
        volcengine_access_key_id="ak",
        volcengine_secret_access_key="sk",
        openai_summary_enabled=True,
    )

    assert "通过 API 面向开发者和企业客户开放" in enriched["summary"]
    assert "后续需要观察实际延迟、成本和企业落地效果" in enriched["summary"]


def test_model_summary_falls_back_when_too_vague(monkeypatch):
    def fake_stable_translate(text, azure_key=None, azure_region=None, **kwargs):
        if text == "OpenAI launches a new model":
            return "OpenAI 发布新模型"
        return (
            "OpenAI 发布的新模型提升了推理、编码和规划能力，面向开发者和企业生产场景。"
            "这意味着团队可以把模型用于代码生成、数据分析和复杂任务拆解。"
        )

    def fake_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini"):
        return "这条新闻意义重大，值得持续关注，后续可能带来深远影响。"

    monkeypatch.setattr("main.translate_to_zh_stable", fake_stable_translate)
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
        summary="The new model improves reasoning, coding and planning for developers and enterprise teams.",
        raw_title="OpenAI launches a new model",
        raw_summary="The new model improves reasoning, coding and planning for developers and enterprise teams.",
    )

    enriched = enrich_item(
        item,
        openai_api_key="test-key",
        openai_base_url="https://api.example.com/v1",
        openai_model="gpt5.4-mini",
        metadata=ArticleMetadata(
            title="OpenAI launches a new model",
            description="The new model improves reasoning, coding and planning for developers and enterprise teams.",
            text=(
                "OpenAI says the release is designed for production use cases, including code generation, "
                "data analysis, customer support automation and internal knowledge base tools."
            ),
        ),
        volcengine_access_key_id="ak",
        volcengine_secret_access_key="sk",
        openai_summary_enabled=True,
    )

    assert "意义重大，值得持续关注" not in enriched["summary"]
    assert "代码生成、数据分析和复杂任务拆解" in enriched["summary"]


def test_final_summary_enhancement_uses_model_for_selected_items_only(monkeypatch):
    calls = []

    def fake_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini", retries=1):
        calls.append((title, api_key, base_url, model, retries))
        return (
            "OpenAI 发布新的推理模型，重点提升代码、数学和规划任务的稳定性，并通过 API 面向开发者和企业客户开放。"
            "这会影响团队构建客服自动化、数据分析和内部知识库等 AI 应用的方式，也会加快同类模型在性能、价格和安全策略上的竞争。"
            "后续需要观察实际延迟、成本和企业落地效果。"
        )

    monkeypatch.setattr("main.summarize_to_zh", fake_summarize)
    items = [
        {
            "title": "OpenAI 发布新模型",
            "summary": "OpenAI 发布的新模型提升了推理、编码和规划能力，面向开发者和企业生产场景。",
            "summary_material": "OpenAI says the release is designed for production use cases and enterprise teams.",
            "summary_source": "本地回退",
            "url": "https://example.com/model",
        }
    ]

    enhance_final_summaries_with_model(
        items,
        openai_api_key="test-key",
        openai_base_url="https://api.example.com/v1",
        openai_summary_model="gpt-4.1-mini",
    )

    assert len(calls) == 1
    assert calls[0] == ("OpenAI 发布新模型", "test-key", "https://api.example.com/v1", "gpt-4.1-mini", 1)
    assert items[0]["summary_source"] == "模型摘要"
    assert "通过 API 面向开发者和企业客户开放" in items[0]["summary"]


def test_final_summary_enhancement_marks_local_fallback_when_model_fails(monkeypatch):
    def fake_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini", retries=1):
        raise RuntimeError("OpenAI request failed with HTTP 503")

    monkeypatch.setattr("main.summarize_to_zh", fake_summarize)
    items = [
        {
            "title": "OpenAI 发布新模型",
            "summary": "OpenAI 发布的新模型提升了推理、编码和规划能力，面向开发者和企业生产场景。",
            "summary_material": "OpenAI says the release is designed for production use cases and enterprise teams.",
            "summary_source": "本地回退",
            "url": "https://example.com/model",
        }
    ]

    enhance_final_summaries_with_model(
        items,
        openai_api_key="test-key",
        openai_base_url="https://api.example.com/v1",
        openai_summary_model="gpt-4.1-mini",
    )

    assert items[0]["summary_source"] == "本地回退"
    assert items[0]["summary"] == "OpenAI 发布的新模型提升了推理、编码和规划能力，面向开发者和企业生产场景。"


def test_final_summary_enhancement_stops_when_model_is_unsupported(monkeypatch):
    calls = []

    def fake_summarize(title, description, api_key, base_url="https://api.openai.com/v1", model="gpt-4.1-mini", retries=1):
        calls.append(title)
        raise RuntimeError("OpenAI request failed with HTTP 400: model is not supported")

    monkeypatch.setattr("main.summarize_to_zh", fake_summarize)
    items = [
        {
            "title": "OpenAI 发布新模型",
            "summary": "OpenAI 发布的新模型提升了推理、编码和规划能力，面向开发者和企业生产场景。",
            "summary_material": "OpenAI says the release is designed for production use cases and enterprise teams.",
            "summary_source": "本地回退",
            "url": "https://example.com/one",
        },
        {
            "title": "Google 发布 AI 更新",
            "summary": "Google 发布 AI 产品更新，面向企业和开发者改进云端应用能力。",
            "summary_material": "Google released AI product updates for enterprise teams and developers.",
            "summary_source": "本地回退",
            "url": "https://example.com/two",
        },
    ]

    enhance_final_summaries_with_model(
        items,
        openai_api_key="test-key",
        openai_base_url="https://api.example.com/v1",
        openai_summary_model="unsupported-model",
    )

    assert calls == ["OpenAI 发布新模型"]
    assert [item["summary_source"] for item in items] == ["本地回退", "本地回退"]


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
    assert len(summary) <= 500


def test_compact_editorial_summary_prefers_information_dense_sentences():
    summary = compact_editorial_summary(
        "这是一篇普通科技新闻。OpenAI 宣布推出新的推理模型，面向开发者开放 API，并强调模型在代码、数学和规划任务上更稳定。"
        "该公司表示，企业客户可以把模型用于客服自动化、数据分析和内部知识库。"
        "这件事值得关注，因为它会影响开发者工具、企业采购和同类模型的竞争节奏。"
        "页面底部还有订阅入口和版权说明。"
    )

    assert "OpenAI 宣布推出新的推理模型" in summary
    assert "企业客户" in summary
    assert "开发者工具" in summary
    assert "订阅入口" not in summary
    assert 100 <= len(summary) <= 500


def test_postprocess_chinese_text_fixes_common_translation_terms():
    reviewed = postprocess_chinese_text(
        "开放人工智能 推出了新的 代理人工智能 产品，聊天GPT 将支持企业用户。",
        "OpenAI launched a new agentic AI product for ChatGPT enterprise users.",
    )

    assert "OpenAI" in reviewed
    assert "智能体 AI" in reviewed
    assert "ChatGPT" in reviewed
    assert "开放人工智能" not in reviewed


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


def test_openai_base_url_candidates_support_plain_and_v1_base_urls():
    assert _openai_chat_url_candidates("https://codexx.dns.army") == [
        "https://codexx.dns.army/chat/completions",
        "https://codexx.dns.army/v1/chat/completions",
    ]
    assert _openai_chat_url_candidates("https://codexx.dns.army/v1") == [
        "https://codexx.dns.army/v1/chat/completions",
    ]


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
