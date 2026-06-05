from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config import load_app_config, load_sources
from dedupe import filter_unsent, mark_sent, mark_sent_url
from fetch_news import (
    dedupe_by_title_similarity,
    fetch_all_news,
    filter_items_by_date,
    is_google_news_placeholder_image,
    is_google_news_url,
    resolve_google_news_url,
    scrape_article_image,
)
from feishu import (
    build_feishu_text_payload,
    payload_to_json,
    send_feishu_webhook,
)
from report import write_report
from summarize import summarize_to_zh
from translate import translate_to_zh_with_base_url


logger = logging.getLogger(__name__)
DOMESTIC_MIN_ITEMS = 4
OVERSEAS_MIN_ITEMS = 6


def yesterday_in_tz(tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    yesterday = now - timedelta(days=1)
    return yesterday.date().isoformat()


def chinese_fallback_title(title: str) -> str:
    return f"海外 AI 新闻：{title}".strip()


def chinese_fallback_summary(summary: str, title: str, source: str) -> str:
    source_text = (summary or title).strip()
    if not source_text:
        return f"这是一条来自 {source} 的海外 AI 新闻，建议打开原文查看详情。"
    return f"这是一条来自 {source} 的海外 AI 新闻。原文要点：{source_text[:260]}"


def enrich_item(item, openai_api_key: str | None, openai_base_url: str, openai_model: str) -> dict[str, str]:
    title_cn = item.title
    summary_cn = item.summary
    title_translated = False
    summary_translated = False
    if item.language.lower().startswith("en"):
        try:
            title_cn = translate_to_zh_with_base_url(item.title, openai_api_key, base_url=openai_base_url, model=openai_model)
            title_translated = title_cn != item.title
        except Exception as exc:
            logger.warning("Title translation failed for %s: %s", item.url, exc)
            title_cn = chinese_fallback_title(item.title)
        summary_source = item.summary or item.raw_summary or item.title
        if summary_source:
            try:
                summary_cn = translate_to_zh_with_base_url(
                    summary_source,
                    openai_api_key,
                    base_url=openai_base_url,
                    model=openai_model,
                )
                summary_translated = summary_cn != summary_source
            except Exception as exc:
                logger.warning("Summary translation failed for %s: %s", item.url, exc)
                summary_cn = chinese_fallback_summary(summary_source, item.title, item.source)
        else:
            summary_cn = title_cn
        if not title_translated and title_cn == item.title:
            title_cn = chinese_fallback_title(item.title)
        if not summary_translated and summary_cn == summary_source:
            summary_cn = chinese_fallback_summary(summary_source, item.title, item.source)
    try:
        summary_cn = summarize_to_zh(
            title_cn,
            summary_cn or item.summary,
            openai_api_key,
            base_url=openai_base_url,
            model=openai_model,
        )
    except Exception as exc:
        logger.warning("Summary generation failed for %s: %s", item.url, exc)
        summary_cn = (summary_cn or item.summary or item.title)[:120].strip()

    return {
        "title": title_cn or item.title,
        "original_title": item.raw_title or item.title,
        "url": item.url,
        "source": item.source,
        "published_at": item.published_at,
        "summary": summary_cn or item.summary or item.title,
        "image_url": item.image_url,
        "image_urls": [item.image_url] if item.image_url else [],
    }


def attach_article_images(items, timeout_seconds: int, retries: int, user_agent: str) -> None:
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
        if existing_image and not is_google_news_placeholder_image(existing_image):
            continue
        scraped_image = scrape_article_image(
            item.url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            user_agent=user_agent,
        )
        item.image_url = scraped_image or ("" if is_google_news_placeholder_image(existing_image) else existing_image)


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
    attach_article_images(
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

    enriched = [enrich_item(item, app.openai_api_key, app.openai_base_url, app.openai_model) for item in unsent_items]
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
