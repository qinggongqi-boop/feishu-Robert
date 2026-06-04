from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import load_app_config, load_sources
from dedupe import filter_unsent, mark_sent
from fetch_news import dedupe_by_title_similarity, fetch_all_news, filter_items_by_date, scrape_article_image
from feishu import (
    build_feishu_payload,
    build_feishu_text_digest_payload,
    build_feishu_text_payload,
    get_tenant_access_token,
    is_keyword_validation_error,
    payload_to_json,
    send_feishu_webhook,
    upload_feishu_image,
)
from summarize import summarize_to_zh
from translate import translate_to_zh_with_base_url


logger = logging.getLogger(__name__)


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
    return f"这是一条来自 {source} 的海外 AI 新闻。原文要点：{source_text[:100]}"


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
        "url": item.url,
        "source": item.source,
        "published_at": item.published_at,
        "summary": summary_cn or item.summary or item.title,
        "image_url": item.image_url,
    }


def attach_article_images(items, timeout_seconds: int, retries: int, user_agent: str) -> None:
    for item in items:
        if item.image_url or not item.url:
            continue
        item.image_url = scrape_article_image(
            item.url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            user_agent=user_agent,
        )


def attach_feishu_image_keys(
    items: list[dict[str, str]],
    app_id: str | None,
    app_secret: str | None,
    max_uploads: int,
    timeout_seconds: int,
    user_agent: str,
) -> None:
    if not app_id or not app_secret or max_uploads <= 0:
        return

    token = get_tenant_access_token(app_id, app_secret)
    uploaded = 0
    for item in items:
        if uploaded >= max_uploads:
            break
        image_url = item.get("cover") or item.get("image_url")
        if not image_url:
            continue
        try:
            item["image_key"] = upload_feishu_image(
                image_url,
                tenant_access_token=token,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
            )
            uploaded += 1
        except Exception as exc:
            logger.warning("Feishu image upload failed for %s: %s", item.get("url", image_url), exc)
    logger.info("Uploaded %d images to Feishu", uploaded)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch AI news and prepare Feishu webhook JSON.")
    parser.add_argument("--sources", default="sources.yaml", help="Path to sources.yaml")
    parser.add_argument("--db", default="data/sent_urls.sqlite3", help="SQLite path for sent URLs")
    parser.add_argument("--send", action="store_true", help="Send payload to Feishu webhook")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD, defaults to yesterday")
    parser.add_argument("--test-feishu", action="store_true", help="Send a minimal Feishu text payload for webhook testing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = load_app_config(sources_path=args.sources, db_path=args.db)
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
    unsent_items = filter_unsent(app.db_path, ranked_items)[: app.max_news_items]
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
    for item in enriched:
        item["tag"] = "海外" if item["source"].lower().startswith("google") or item["source"].lower().startswith("reuters") else "国内"
        item["conclusion"] = item.get("summary", item["title"])[:80]
        if item.get("image_url"):
            item["cover"] = item["image_url"]

    attach_feishu_image_keys(
        enriched,
        app_id=app.feishu_app_id,
        app_secret=app.feishu_app_secret,
        max_uploads=app.max_image_uploads,
        timeout_seconds=app.fetch_timeout_seconds,
        user_agent=app.user_agent,
    )

    message_format = app.feishu_message_format
    if any(item.get("image_key") for item in enriched):
        message_format = "card"

    payload = build_feishu_payload(
        enriched,
        title=f"昨日 AI 新闻简报｜{target_date}",
        total_count=len(fetch_result.items),
        selected_count=len(enriched),
        message_format=message_format,
        keyword=app.feishu_keyword,
    )

    print(payload_to_json(payload))

    if args.send:
        if not app.feishu_webhook_url:
            raise RuntimeError("FEISHU_WEBHOOK_URL is not set")
        try:
            response_body = send_feishu_webhook(app.feishu_webhook_url, payload)
        except Exception as exc:
            if not is_keyword_validation_error(exc):
                raise
            logger.warning("Feishu post payload failed keyword validation, falling back to text digest")
            fallback_payload = build_feishu_text_digest_payload(
                enriched,
                title=f"昨日 AI 新闻简报｜{target_date}",
                keyword=app.feishu_keyword,
            )
            response_body = send_feishu_webhook(app.feishu_webhook_url, fallback_payload)
        logger.info("Feishu webhook response: %s", response_body or "<empty>")
        for item in unsent_items:
            mark_sent(app.db_path, item)
        logger.info("Send status: success")
    else:
        logger.info("Send status: skipped (dry run)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
