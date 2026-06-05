from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config import load_app_config, load_sources
from dedupe import filter_unsent, mark_sent, mark_sent_url
from fetch_news import (
    ArticleMetadata,
    dedupe_by_title_similarity,
    fetch_all_news,
    filter_items_by_date,
    is_google_news_placeholder_image,
    is_google_news_url,
    resolve_google_news_url,
    scrape_article_metadata,
)
from feishu import (
    build_feishu_text_payload,
    payload_to_json,
    send_feishu_webhook,
)
from report import write_report
from summarize import summarize_to_zh
from translate import translate_to_zh_fallback, translate_to_zh_with_base_url


logger = logging.getLogger(__name__)
DOMESTIC_MIN_ITEMS = 4
OVERSEAS_MIN_ITEMS = 6


def looks_mostly_english(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    ascii_letters = [char for char in letters if char.isascii()]
    return len(ascii_letters) / len(letters) > 0.72


TERM_TRANSLATIONS = [
    (r"\bagentic AI\b", "智能体 AI"),
    (r"\bartificial intelligence\b", "人工智能"),
    (r"\bgenerative AI\b", "生成式 AI"),
    (r"\blarge language models?\b", "大语言模型"),
    (r"\bAI models?\b", "AI 模型"),
    (r"\bAI systems?\b", "AI 系统"),
    (r"\bAI skills?\b", "AI 技能"),
    (r"\bAI lab\b", "AI 实验室"),
    (r"\bAI practices?\b", "AI 做法"),
    (r"\bdata centers?\b", "数据中心"),
    (r"\bcloud\b", "云计算"),
    (r"\bchips?\b", "芯片"),
    (r"\bsemiconductors?\b", "半导体"),
    (r"\bregulation\b", "监管"),
    (r"\bsafety\b", "安全"),
    (r"\bpolicy\b", "政策"),
    (r"\bpropaganda\b", "宣传操纵"),
    (r"\breal-world operations?\b", "真实业务运营"),
    (r"\bhuman-centered\b", "以人为中心"),
    (r"\bhealth capabilities?\b", "健康能力"),
    (r"\bbiological weapon\b", "生物武器"),
    (r"\bDNA screening\b", "DNA 筛查"),
    (r"\btask management\b", "任务管理"),
    (r"\bfraud detection\b", "欺诈检测"),
    (r"\bcompetition probe\b", "竞争调查"),
    (r"\bpremium salaries\b", "高薪溢价"),
    (r"\bstartup\b", "创业公司"),
    (r"\bstartups\b", "创业公司"),
    (r"\bCEO\b", "CEO"),
    (r"\bAGI\b", "通用人工智能"),
]


def strip_source_suffix(title: str) -> str:
    return re.sub(r"\s+-\s+[^-]{2,80}$", "", title).strip()


def strip_chinese_source_suffix(title: str) -> str:
    return re.sub(r"\s*[-－]\s*[^-－]{2,24}$", "", title).strip()


def apply_term_glossary(text: str) -> str:
    result = text
    for pattern, replacement in TERM_TRANSLATIONS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    result = result.replace("’s", " 的").replace("'s", " 的")
    result = result.replace("“", "「").replace("”", "」")
    return " ".join(result.split())


def heuristic_english_title_to_zh(title: str) -> str:
    clean_title = strip_source_suffix(title)
    normalized = apply_term_glossary(clean_title)
    patterns = [
        (r"^Study:\s*(.+)$", "研究：{0}"),
        (r"^(.+?) launches (.+?) for (.+)$", "{0}推出面向{2}的{1}"),
        (r"^(.+?) launches (.+)$", "{0}推出{1}"),
        (r"^(.+?) faces (.+?) over (.+)$", "{0}因{2}面临{1}"),
        (r"^(.+?) call for (.+)$", "{0}呼吁{1}"),
        (r"^(.+?) calls for (.+)$", "{0}呼吁{1}"),
        (r"^(.+?) may soon (.+)$", "{0}可能很快{1}"),
        (r"^(.+?) says (.+)$", "{0}表示：{1}"),
        (r"^(.+?) driving (.+)$", "{0}推动{1}"),
    ]
    for pattern, template in patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return template.format(*(part.strip() for part in match.groups()))
    if re.search(r"[\u4e00-\u9fff]", normalized):
        return normalized
    return f"AI 科技动态：{normalized}"


def yesterday_in_tz(tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    yesterday = now - timedelta(days=1)
    return yesterday.date().isoformat()


def chinese_fallback_title(title: str) -> str:
    translated = translate_to_zh_fallback(title)
    if translated and translated != title:
        return strip_chinese_source_suffix(translated)
    return heuristic_english_title_to_zh(title)


def chinese_fallback_summary(summary: str, title: str, source: str) -> str:
    source_text = " ".join((summary or title).split())
    if not source_text:
        return f"这篇来自 {source} 的报道涉及 AI 或科技行业的重要动态，建议结合原文进一步查看事件细节、相关公司表态以及后续影响。"
    translated = translate_to_zh_fallback(source_text)
    clean_text = translated if translated and translated != source_text else apply_term_glossary(source_text)
    clean_text = clean_summary_material(clean_text)
    clean_text = clean_text.rstrip("。；;,.，")
    base = (
        f"据 {source} 报道，{clean_text}。"
        "这条消息的看点在于，它反映出 AI 技术正在从模型能力展示继续走向产业应用、组织决策或监管讨论。"
        "后续值得关注相关公司是否披露更多产品细节、商业化路径和落地效果，以及这会如何影响行业竞争和用户体验。"
    )
    return base[:320].strip()


def clean_summary_material(text: str) -> str:
    noise_patterns = [
        r"\bBNN News BNN\b.*?(?=研究|人工智能|AI|据|这)",
        r"\bMain navigation\b.*?(?=\d|AI|Artificial|The|人工智能)",
        r"\bHome Top Stories Latest Stories\b",
        r"\bAdvertisement\b",
        r"\bFacebook Twitter\b",
        r"\bSearch Home\b",
        r"\b2 -MIN READ\b.*?\bListen\b",
        r"主导航.*?(?=\d|人工智能|AI)",
        r"主页 热门故事 最新故事",
        r"广告 搜索",
    ]
    cleaned = text
    for pattern in noise_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def polish_summary(summary: str, source_text: str, title: str, source: str, force_fallback: bool = False) -> str:
    clean_summary = " ".join((summary or "").split())
    if force_fallback or looks_mostly_english(clean_summary):
        clean_summary = chinese_fallback_summary(source_text, title, source)
    clean_summary = clean_summary_material(clean_summary)
    if len(clean_summary) < 180:
        clean_summary = (
            f"{clean_summary} "
            "这条新闻的重点不只在单个事件本身，也在于它反映出 AI 技术、资本投入、产品落地或监管环境正在继续变化。"
            "后续可以关注相关公司是否公布更多细节，以及这一变化会怎样影响行业竞争和实际应用。"
        ).strip()
    return clean_summary[:330].rstrip("，。；;,. ") + "。"


def build_summary_source(item, metadata: ArticleMetadata | None) -> str:
    parts = [
        metadata.description if metadata else "",
        metadata.text if metadata else "",
        item.summary,
        item.raw_summary,
    ]
    clean_parts: list[str] = []
    for part in parts:
        text = " ".join((part or "").split())
        if text and text not in clean_parts:
            clean_parts.append(text)
    if not clean_parts:
        clean_parts.append((metadata.title if metadata and metadata.title else item.title).strip())
    return "\n".join(clean_parts)[:2200]


def enrich_item(item, openai_api_key: str | None, openai_base_url: str, openai_model: str, metadata: ArticleMetadata | None = None) -> dict[str, str]:
    original_title = (metadata.title if metadata and metadata.title else item.raw_title or item.title).strip()
    title_cn = original_title
    summary_source = build_summary_source(item, metadata)
    summary_cn = summary_source or item.summary
    title_translated = False
    if item.language.lower().startswith("en"):
        try:
            title_cn = translate_to_zh_with_base_url(original_title, openai_api_key, base_url=openai_base_url, model=openai_model)
            title_translated = title_cn != original_title
        except Exception as exc:
            logger.warning("Title translation failed for %s: %s", item.url, exc)
            title_cn = chinese_fallback_title(original_title)
        if not title_translated and title_cn == original_title:
            title_cn = chinese_fallback_title(original_title)
    try:
        summary_cn = summarize_to_zh(
            title_cn,
            summary_source or summary_cn or item.summary,
            openai_api_key,
            base_url=openai_base_url,
            model=openai_model,
        )
    except Exception as exc:
        logger.warning("Summary generation failed for %s: %s", item.url, exc)
        summary_cn = chinese_fallback_summary(summary_source, title_cn or original_title, item.source)
    summary_cn = polish_summary(
        summary_cn,
        source_text=summary_source,
        title=title_cn or original_title,
        source=item.source,
        force_fallback=item.language.lower().startswith("en") and looks_mostly_english(summary_cn),
    )

    return {
        "title": title_cn or item.title,
        "original_title": original_title,
        "url": item.url,
        "source": item.source,
        "published_at": item.published_at,
        "summary": summary_cn or chinese_fallback_summary(summary_source, title_cn or original_title, item.source),
        "image_url": item.image_url,
        "image_urls": [item.image_url] if item.image_url else [],
    }


def attach_article_metadata(items, timeout_seconds: int, retries: int, user_agent: str) -> dict[str, ArticleMetadata]:
    metadata_by_url: dict[str, ArticleMetadata] = {}
    for item in items:
        if not item.url:
            continue
        if is_google_news_url(item.url):
            resolved_url = resolve_google_news_url(
                item.url,
                timeout_seconds=timeout_seconds,
                retries=retries,
                user_agent=user_agent,
            )
            if resolved_url != item.url:
                item.url = resolved_url
        existing_image = item.image_url
        metadata = scrape_article_metadata(
            item.url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            user_agent=user_agent,
        )
        metadata_by_url[item.url] = metadata
        if metadata.image_url:
            item.image_url = metadata.image_url
        elif existing_image and not is_google_news_placeholder_image(existing_image):
            item.image_url = existing_image
        else:
            item.image_url = ""
    return metadata_by_url


def is_overseas_item(item) -> bool:
    return item.language.lower().startswith("en")


def select_balanced_items(items, max_items: int) -> list:
    overseas_items = [item for item in items if is_overseas_item(item)]
    domestic_items = [item for item in items if not is_overseas_item(item)]
    selected: list = []
    seen_urls: set[str] = set()

    def add_from(candidates, limit: int) -> None:
        added = 0
        for candidate in candidates:
            if len(selected) >= max_items or added >= limit:
                break
            if candidate.url in seen_urls:
                continue
            selected.append(candidate)
            seen_urls.add(candidate.url)
            added += 1

    add_from(overseas_items, min(OVERSEAS_MIN_ITEMS, max_items))
    add_from(domestic_items, min(DOMESTIC_MIN_ITEMS, max_items - len(selected)))
    for candidate in items:
        if len(selected) >= max_items:
            break
        if candidate.url in seen_urls:
            continue
        selected.append(candidate)
        seen_urls.add(candidate.url)
    return selected


def build_report_notification_text(report_url: str, selected_count: int) -> str:
    return f"昨日 AI 科技新闻已更新，共 {selected_count} 条，请查阅：\n{report_url}"


def write_report_meta(
    meta_path: str | Path,
    *,
    target_date: str,
    report_url: str,
    selected_count: int,
    total_count: int,
    items,
) -> Path:
    path = Path(meta_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "target_date": target_date,
        "report_url": report_url,
        "selected_count": selected_count,
        "total_count": total_count,
        "items": [
            {
                "url": item.url,
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at,
            }
            for item in items
            if item.url
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def notify_from_meta(meta_path: str | Path, db_path: str | Path, webhook_url: str | None, send: bool) -> dict:
    data = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    payload = build_feishu_text_payload(
        build_report_notification_text(
            report_url=data["report_url"],
            selected_count=int(data.get("selected_count", 0)),
        )
    )
    print(payload_to_json(payload))
    if not send:
        logger.info("Send status: skipped (dry run)")
        return payload
    if not webhook_url:
        raise RuntimeError("FEISHU_WEBHOOK_URL is not set")
    response_body = send_feishu_webhook(webhook_url, payload)
    logger.info("Feishu webhook response: %s", response_body or "<empty>")
    for item in data.get("items", []):
        mark_sent_url(
            db_path,
            url=item.get("url", ""),
            title=item.get("title", ""),
            source=item.get("source", ""),
            published_at=item.get("published_at", ""),
        )
    logger.info("Marked sent URLs: %d", len(data.get("items", [])))
    logger.info("Send status: success")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch AI news and prepare Feishu webhook JSON.")
    parser.add_argument("--sources", default="sources.yaml", help="Path to sources.yaml")
    parser.add_argument("--db", default="data/sent_urls.sqlite3", help="SQLite path for sent URLs")
    parser.add_argument("--send", action="store_true", help="Send payload to Feishu webhook")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD, defaults to yesterday")
    parser.add_argument("--test-feishu", action="store_true", help="Send a minimal Feishu text payload for webhook testing")
    parser.add_argument("--write-meta", default=None, help="Write report notification metadata JSON")
    parser.add_argument("--notify-meta", default=None, help="Send Feishu link notification from metadata JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = load_app_config(sources_path=args.sources, db_path=args.db)
    if args.notify_meta:
        notify_from_meta(args.notify_meta, app.db_path, app.feishu_webhook_url, args.send)
        return 0

    if args.test_feishu:
        payload = build_feishu_text_payload(f"{app.feishu_keyword}｜Feishu webhook test: bot is reachable.")
        print(payload_to_json(payload))
        if args.send:
            if not app.feishu_webhook_url:
                raise RuntimeError("FEISHU_WEBHOOK_URL is not set")
            response_body = send_feishu_webhook(app.feishu_webhook_url, payload)
            logger.info("Feishu webhook response: %s", response_body or "<empty>")
            logger.info("Send status: success")
        else:
            logger.info("Send status: skipped (dry run)")
        return 0

    sources = load_sources(args.sources)
    target_date = args.date or yesterday_in_tz(app.timezone)

    fetch_result = fetch_all_news(
        sources,
        app.timezone,
        timeout_seconds=app.fetch_timeout_seconds,
        retries=app.fetch_retries,
        user_agent=app.user_agent,
    )
    dated_items = filter_items_by_date(fetch_result.items, target_date)
    ranked_items = dedupe_by_title_similarity(dated_items, threshold=0.85)
    unsent_items = select_balanced_items(filter_unsent(app.db_path, ranked_items), app.max_news_items)
    metadata_by_url = attach_article_metadata(
        unsent_items,
        timeout_seconds=app.fetch_timeout_seconds,
        retries=1,
        user_agent=app.user_agent,
    )

    logger.info("Fetched %d items from %d sources", len(fetch_result.items), len(sources))
    logger.info("After date filter (%s): %d items", target_date, len(dated_items))
    logger.info("After title dedupe: %d items", len(ranked_items))
    logger.info("Selected for sending: %d items", len(unsent_items))
    logger.info("Max news items: %d", app.max_news_items)
    if fetch_result.failed_sources:
        logger.warning("Failed sources: %s", ", ".join(fetch_result.failed_sources))
    else:
        logger.info("Failed sources: none")
    for source_name, count in fetch_result.per_source_counts.items():
        logger.info("Source %s fetched %d items", source_name, count)

    enriched = [
        enrich_item(
            item,
            app.openai_api_key,
            app.openai_base_url,
            app.openai_model,
            metadata=metadata_by_url.get(item.url),
        )
        for item in unsent_items
    ]
    for item, original_item in zip(enriched, unsent_items):
        item["tag"] = "海外" if is_overseas_item(original_item) else "国内"
        item["conclusion"] = item.get("summary", item["title"])[:80]
        if item.get("image_url"):
            item["cover"] = item["image_url"]

    generated_at = datetime.now(ZoneInfo(app.timezone)).strftime("%Y-%m-%d %H:%M %Z")
    report_path = write_report(
        enriched,
        output_dir=app.report_output_dir,
        target_date=target_date,
        total_count=len(fetch_result.items),
        selected_count=len(enriched),
        generated_at=generated_at,
    )
    report_url = f"{app.report_base_url}/{target_date}.html"
    logger.info("Report path: %s", report_path)
    logger.info("Report url: %s", report_url)

    if args.write_meta:
        meta_path = write_report_meta(
            args.write_meta,
            target_date=target_date,
            report_url=report_url,
            selected_count=len(enriched),
            total_count=len(fetch_result.items),
            items=unsent_items,
        )
        logger.info("Report metadata path: %s", meta_path)

    payload = build_feishu_text_payload(build_report_notification_text(report_url, len(enriched)))
    print(payload_to_json(payload))

    if args.send:
        if not app.feishu_webhook_url:
            raise RuntimeError("FEISHU_WEBHOOK_URL is not set")
        response_body = send_feishu_webhook(app.feishu_webhook_url, payload)
        logger.info("Feishu webhook response: %s", response_body or "<empty>")
        for item in unsent_items:
            mark_sent(app.db_path, item)
        logger.info("Send status: success")
    else:
        logger.info("Send status: skipped (dry run)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
