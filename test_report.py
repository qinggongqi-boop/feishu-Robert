from __future__ import annotations

from report import build_report_html, write_report


def test_report_html_contains_news_fields_and_images():
    html = build_report_html(
        items=[
            {
                "title": "中文主标题",
                "original_title": "Original English Title",
                "summary": "这是一段中文概述，介绍新闻的关键事实、背景和影响，方便读者快速理解这条科技新闻为什么值得关注。",
                "source": "Google News AI Global",
                "url": "https://example.com/article",
                "tag": "海外",
                "image_urls": ["https://example.com/cover-1.jpg", "https://example.com/cover-2.jpg"],
            }
        ],
        target_date="2026-06-05",
        total_count=30,
        selected_count=1,
        generated_at="2026-06-06 09:13 CST",
    )

    assert "昨日 AI 科技新闻" in html
    assert "中文主标题" in html
    assert "Original English Title" in html
    assert "Google News AI Global" in html
    assert "https://example.com/article" in html
    assert "https://example.com/cover-1.jpg" in html
    assert "https://example.com/cover-2.jpg" in html
    assert "精选 1 条" in html


def test_report_html_has_mobile_overflow_guards_and_keeps_long_summary():
    long_summary = (
        "OpenAI 发布新的推理模型，面向开发者开放 API，并强调模型在代码、数学和规划任务上更稳定。"
        "企业客户可以把模型用于客服自动化、数据分析和内部知识库，这会影响开发者工具、企业采购和同类模型竞争节奏。"
        "后续值得关注模型价格、实际延迟、安全策略和生态伙伴是否跟进。"
    )
    html = build_report_html(
        items=[
            {
                "title": "这是一个非常长的中文主标题用来模拟手机端可能撑开页面的新闻标题",
                "original_title": "VeryLongOriginalEnglishTitleWithoutSpacesThatCouldBreakMobileLayouts",
                "summary": long_summary,
                "source": "Google News AI Global",
                "url": "https://example.com/article",
                "tag": "海外",
                "image_urls": [],
            }
        ],
        target_date="2026-06-05",
        total_count=30,
        selected_count=1,
        generated_at="2026-06-06 09:13 CST",
    )

    assert long_summary in html
    assert "overflow-x: hidden" in html
    assert "minmax(0, 1fr)" in html
    assert "overflow-wrap: anywhere" in html
    assert "@media (max-width: 420px)" in html


def test_write_report_generates_latest_index_redirect(tmp_path):
    report_path = write_report(
        items=[],
        output_dir=tmp_path,
        target_date="2026-06-05",
        total_count=0,
        selected_count=0,
        generated_at="2026-06-06 09:13 CST",
    )

    index_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert report_path == tmp_path / "2026-06-05.html"
    assert report_path.exists()
    assert "url=2026-06-05.html" in index_html
