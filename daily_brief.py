from __future__ import annotations

import argparse
import base64
import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import hmac
import html
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import feedparser
import requests

from feishu import build_feishu_text_payload, send_feishu_webhook
from translate import _call_openai_chat


DEFAULT_TOPICS = (
    "AI / 模型 / Codex / Agent",
    "跨境电商 / Meta广告 / 爆款素材",
    "全球商业 / 科技公司动态",
)
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; Feishu-Daily-Brief/1.0; +https://github.com/qinggongqi-boop/feishu-Robert)"
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "spm",
    "from",
    "src",
}

logger = logging.getLogger("daily_brief")


@dataclass(frozen=True)
class FeedSource:
    topic: str
    source: str
    url: str


@dataclass
class BriefArticle:
    topic: str
    source: str
    title: str
    url: str
    summary: str
    published_at: datetime | None
    ref_id: str = ""


@dataclass(frozen=True)
class BriefConfig:
    feeds_path: Path
    lookback_hours: int
    max_articles_per_topic: int
    timezone_name: str
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str
    feishu_webhook: str | None
    feishu_secret: str | None
    text_only: bool
    timeout_seconds: int
    retries: int
    user_agent: str


@dataclass
class FetchSummary:
    articles: list[BriefArticle]
    failed_sources: list[str]
    per_topic_counts: dict[str, int]
    source_count: int


class BriefConfigError(RuntimeError):
    pass


class MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def setup_logging(log_dir: str | Path = "logs") -> None:
    path = Path(log_dir)
    path.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.addFilter(MaxLevelFilter(logging.INFO))
    stdout_handler.setFormatter(formatter)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)

    out_file = logging.FileHandler(path / "dailybrief.out.log", encoding="utf-8")
    out_file.setLevel(logging.INFO)
    out_file.addFilter(MaxLevelFilter(logging.INFO))
    out_file.setFormatter(formatter)

    err_file = logging.FileHandler(path / "dailybrief.err.log", encoding="utf-8")
    err_file.setLevel(logging.WARNING)
    err_file.setFormatter(formatter)

    root.addHandler(stdout_handler)
    root.addHandler(stderr_handler)
    root.addHandler(out_file)
    root.addHandler(err_file)


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise BriefConfigError(f"{name} must be an integer, got {value!r}") from exc


def load_config(args: argparse.Namespace) -> BriefConfig:
    feeds_path = Path(args.feeds or os.getenv("FEEDS_JSON", "feeds.json"))
    lookback_hours = int(args.lookback_hours if args.lookback_hours is not None else env_int("LOOKBACK_HOURS", 30))
    max_per_topic = int(args.max_per_topic if args.max_per_topic is not None else env_int("MAX_ARTICLES_PER_TOPIC", 10))
    openai_base_url = (
        os.getenv("OPENAI_SUMMARY_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    )
    openai_model = os.getenv("OPENAI_SUMMARY_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4.1-mini"
    return BriefConfig(
        feeds_path=feeds_path,
        lookback_hours=lookback_hours,
        max_articles_per_topic=max_per_topic,
        timezone_name=os.getenv("APP_TIMEZONE", "Asia/Shanghai"),
        openai_api_key=os.getenv("OPENAI_SUMMARY_API_KEY") or os.getenv("OPENAI_API_KEY"),
        openai_base_url=openai_base_url,
        openai_model=openai_model,
        feishu_webhook=os.getenv("FEISHU_WEBHOOK") or os.getenv("FEISHU_WEBHOOK_URL"),
        feishu_secret=os.getenv("FEISHU_SECRET"),
        text_only=bool(args.text_only),
        timeout_seconds=env_int("FETCH_TIMEOUT_SECONDS", 15),
        retries=env_int("FETCH_RETRIES", 3),
        user_agent=os.getenv("NEWS_USER_AGENT", DEFAULT_USER_AGENT),
    )


def validate_config(config: BriefConfig, *, test_mode: bool = False) -> None:
    if not config.feishu_webhook:
        raise BriefConfigError("Missing FEISHU_WEBHOOK. You can also use the legacy FEISHU_WEBHOOK_URL.")
    if not test_mode and not config.openai_api_key:
        raise BriefConfigError("Missing OPENAI_API_KEY. The formal daily brief needs an LLM call.")
    if config.lookback_hours <= 0:
        raise BriefConfigError("LOOKBACK_HOURS must be greater than 0.")
    if config.max_articles_per_topic <= 0:
        raise BriefConfigError("MAX_ARTICLES_PER_TOPIC must be greater than 0.")


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in TRACKING_PARAMS]
    rebuilt = parsed._replace(query=urlencode(query), fragment="")
    return urlunparse(rebuilt)


def normalize_title(title: str) -> str:
    text = html.unescape(title or "").lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_html(text: str) -> str:
    value = html.unescape(text or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def parse_entry_datetime(entry: dict, tz: ZoneInfo) -> datetime | None:
    for key in ("published", "updated", "created"):
        value = entry.get(key)
        if value:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(tz)
            except Exception:
                continue
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                parsed = datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
                return parsed.astimezone(tz)
            except Exception:
                continue
    return None


def load_feeds(path: str | Path) -> list[FeedSource]:
    feeds_path = Path(path)
    try:
        raw = json.loads(feeds_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BriefConfigError(f"Invalid JSON in {feeds_path}: {exc}") from exc
    except FileNotFoundError as exc:
        raise BriefConfigError(f"Feeds file not found: {feeds_path}") from exc
    if not isinstance(raw, list):
        raise BriefConfigError("feeds.json must be a JSON array.")

    feeds: list[FeedSource] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise BriefConfigError(f"Feed item #{index} must be an object.")
        topic = str(item.get("topic", "")).strip()
        source = str(item.get("source", "")).strip()
        url = str(item.get("url", "")).strip()
        if not topic or not source or not url:
            raise BriefConfigError(f"Feed item #{index} must include topic, source and url.")
        feeds.append(FeedSource(topic=topic, source=source, url=url))
    return feeds


def request_bytes(url: str, *, timeout_seconds: int, retries: int, user_agent: str) -> bytes:
    headers = {"User-Agent": user_agent, "Accept": "application/rss+xml, application/xml, text/xml, */*"}
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 * attempt, 5))
    assert last_error is not None
    raise last_error


def entry_url(entry: dict) -> str:
    for key in ("link", "id", "guid"):
        value = entry.get(key)
        if value:
            return canonicalize_url(str(value))
    return ""


def entry_summary(entry: dict) -> str:
    for key in ("summary", "description"):
        value = entry.get(key)
        if value:
            return strip_html(str(value))[:500]
    return ""


def fetch_feed_articles(source: FeedSource, config: BriefConfig) -> list[BriefArticle]:
    tz = ZoneInfo(config.timezone_name)
    body = request_bytes(
        source.url,
        timeout_seconds=config.timeout_seconds,
        retries=config.retries,
        user_agent=config.user_agent,
    )
    feed = feedparser.parse(body)
    if getattr(feed, "bozo", False):
        logger.warning("RSS parsed with warnings: %s (%s)", source.source, getattr(feed, "bozo_exception", "unknown"))

    articles: list[BriefArticle] = []
    for entry in getattr(feed, "entries", []):
        title = strip_html(str(entry.get("title", "")))
        url = entry_url(entry)
        if not title or not url:
            continue
        articles.append(
            BriefArticle(
                topic=source.topic,
                source=source.source,
                title=title,
                url=url,
                summary=entry_summary(entry),
                published_at=parse_entry_datetime(entry, tz),
            )
        )
    return articles


def dedupe_articles(articles: Iterable[BriefArticle]) -> list[BriefArticle]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    deduped: list[BriefArticle] = []
    for article in articles:
        normalized_url = canonicalize_url(article.url)
        normalized_title = normalize_title(article.title)
        if normalized_url in seen_urls or normalized_title in seen_titles:
            continue
        seen_urls.add(normalized_url)
        seen_titles.add(normalized_title)
        article.url = normalized_url
        deduped.append(article)
    return deduped


def filter_by_lookback(
    articles: Iterable[BriefArticle],
    *,
    lookback_hours: int,
    now: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> list[BriefArticle]:
    tz = ZoneInfo(timezone_name)
    current = now.astimezone(tz) if now else datetime.now(tz)
    cutoff = current - timedelta(hours=lookback_hours)
    kept: list[BriefArticle] = []
    for article in articles:
        if article.published_at is None or article.published_at >= cutoff:
            kept.append(article)
    return kept


def sort_articles(articles: Iterable[BriefArticle]) -> list[BriefArticle]:
    return sorted(
        articles,
        key=lambda article: (
            article.published_at is not None,
            article.published_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )


def limit_articles_per_topic(articles: Iterable[BriefArticle], max_per_topic: int) -> list[BriefArticle]:
    counts: dict[str, int] = {}
    selected: list[BriefArticle] = []
    for article in sort_articles(articles):
        count = counts.get(article.topic, 0)
        if count >= max_per_topic:
            continue
        selected.append(article)
        counts[article.topic] = count + 1
    return selected


def fetch_and_filter(feeds: list[FeedSource], config: BriefConfig) -> FetchSummary:
    logger.info("Start fetching %s feeds, lookback_hours=%s", len(feeds), config.lookback_hours)
    all_articles: list[BriefArticle] = []
    failed_sources: list[str] = []
    for feed in feeds:
        try:
            articles = fetch_feed_articles(feed, config)
            logger.info("Fetched %s articles from %s", len(articles), feed.source)
            all_articles.extend(articles)
        except Exception as exc:
            failed_sources.append(feed.source)
            logger.warning("Failed to fetch RSS source %s: %s", feed.source, exc, exc_info=True)

    filtered = filter_by_lookback(
        dedupe_articles(all_articles),
        lookback_hours=config.lookback_hours,
        timezone_name=config.timezone_name,
    )
    limited = limit_articles_per_topic(filtered, config.max_articles_per_topic)
    per_topic_counts: dict[str, int] = {topic: 0 for topic in DEFAULT_TOPICS}
    for article in limited:
        per_topic_counts[article.topic] = per_topic_counts.get(article.topic, 0) + 1

    logger.info("Fetched total=%s, after_filter=%s, selected=%s", len(all_articles), len(filtered), len(limited))
    for topic, count in per_topic_counts.items():
        logger.info("Topic selected count: %s = %s", topic, count)
    if failed_sources:
        logger.warning("Failed sources: %s", ", ".join(failed_sources))
    return FetchSummary(
        articles=limited,
        failed_sources=failed_sources,
        per_topic_counts=per_topic_counts,
        source_count=len(feeds),
    )


def assign_reference_ids(articles: list[BriefArticle]) -> list[BriefArticle]:
    for index, article in enumerate(articles, start=1):
        article.ref_id = f"S{index}"
    return articles


def format_article_for_prompt(article: BriefArticle) -> str:
    published = article.published_at.isoformat() if article.published_at else "未知"
    summary = article.summary or "RSS 未提供摘要"
    return (
        f"[{article.ref_id}]\n"
        f"topic: {article.topic}\n"
        f"source: {article.source}\n"
        f"published_at: {published}\n"
        f"title: {article.title}\n"
        f"summary: {summary}\n"
        f"url: {article.url}"
    )


def build_llm_prompt(articles: list[BriefArticle], report_date: str) -> str:
    source_blocks = "\n\n".join(format_article_for_prompt(article) for article in articles)
    return f"""
请基于下面 RSS 资讯，生成一份中文《每日增长情报简报｜{report_date}》。

使用者背景：
- 使用者做美国市场服装独立站。
- 主要投放 Meta 广告。
- 关注爆款广告素材、AI 视频、Agent 自动化、Codex 工具链、跨境电商增长机会。

写作目标：
- 这不是普通新闻聚合，而是增长情报、创意趋势和机会识别。
- 优先提炼新工具、新机会、爆款创意形式、广告钩子、行业趋势、对职业成长的启发。
- 不要空泛，不要营销腔，不要大段复制英文。
- 每条重要信息后尽量标注来源编号，例如 [S1]。
- 如果某个板块没有足够高价值信息，明确写“今日未抓到足够高价值更新”。

输出必须严格使用下面结构：

每日增长情报简报｜{report_date}

一、今日最重要的 3–5 条结论

1. ...
2. ...
3. ...

二、AI / 模型 / Codex / Agent

关键变化：
- ...

为什么重要：
- ...

可以借鉴/测试的动作：
- ...

三、跨境电商 / Meta广告 / 爆款素材

关键变化：
- ...

为什么重要：
- ...

可以借鉴/测试的动作：
- ...

四、全球商业 / 科技公司动态

关键变化：
- ...

为什么重要：
- ...

可以借鉴/测试的动作：
- ...

五、今天可以做的一件小事

- ...

可用资讯如下：

{source_blocks}
""".strip()


def generate_brief_text(articles: list[BriefArticle], config: BriefConfig, report_date: str) -> str:
    if not articles:
        raise RuntimeError("No articles available for LLM brief generation.")
    if not config.openai_api_key:
        raise BriefConfigError("Missing OPENAI_API_KEY. The formal daily brief needs an LLM call.")
    logger.info("Calling LLM model=%s base_url=%s", config.openai_model, config.openai_base_url)
    system_prompt = (
        "你是一名中文增长情报编辑，擅长把科技、AI、广告、电商资讯整理成"
        "对跨境电商增长负责人有用的机会判断和可执行建议。必须事实谨慎，不编造。"
    )
    user_prompt = build_llm_prompt(articles, report_date)
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            brief = _call_openai_chat(
                api_key=config.openai_api_key,
                base_url=config.openai_base_url,
                model=config.openai_model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.2,
                timeout_seconds=90,
            )
            logger.info("LLM call succeeded, brief_chars=%s", len(brief))
            return brief.strip()
        except Exception as exc:
            last_error = exc
            if attempt >= 2:
                break
            logger.warning("LLM call failed on attempt %s, retrying once: %s", attempt, exc)
            time.sleep(3)
    assert last_error is not None
    raise last_error


def feishu_sign(secret: str, timestamp: int | None = None) -> tuple[str, str]:
    ts = str(timestamp or int(time.time()))
    string_to_sign = f"{ts}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
    return ts, base64.b64encode(digest).decode("utf-8")


def apply_feishu_signature(payload: dict, secret: str | None) -> dict:
    if not secret:
        return payload
    timestamp, sign = feishu_sign(secret)
    signed = dict(payload)
    signed["timestamp"] = timestamp
    signed["sign"] = sign
    return signed


def line_to_post_block(line: str) -> list[dict[str, object]]:
    text = line.rstrip()
    if not text:
        return [{"tag": "text", "text": ""}]
    return [{"tag": "text", "text": text}]


def build_brief_post_payload(
    brief_text: str,
    articles: list[BriefArticle],
    report_date: str,
    *,
    max_references: int = 12,
) -> dict:
    content: list[list[dict[str, object]]] = [line_to_post_block(line) for line in brief_text.splitlines()]
    content.append([{"tag": "text", "text": ""}])
    content.append([{"tag": "text", "text": "参考来源"}])
    for article in articles[:max_references]:
        content.append(
            [
                {"tag": "text", "text": f"[{article.ref_id}] {article.source}｜"},
                {"tag": "a", "text": article.title[:80], "href": article.url},
            ]
        )
    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"每日增长情报简报｜{report_date}",
                    "content": content,
                }
            }
        },
    }


def build_brief_text_payload(brief_text: str, articles: list[BriefArticle], *, max_references: int = 12) -> dict:
    lines = [brief_text.strip(), "", "参考来源"]
    for article in articles[:max_references]:
        lines.append(f"[{article.ref_id}] {article.source}｜{article.title}：{article.url}")
    return build_feishu_text_payload("\n".join(lines).strip())


def send_brief_to_feishu(
    config: BriefConfig,
    brief_text: str,
    articles: list[BriefArticle],
    report_date: str,
) -> str:
    if not config.feishu_webhook:
        raise BriefConfigError("Missing FEISHU_WEBHOOK.")

    text_payload = apply_feishu_signature(build_brief_text_payload(brief_text, articles), config.feishu_secret)
    if config.text_only:
        logger.info("Sending Feishu text-only message")
        return send_feishu_webhook(config.feishu_webhook, text_payload)

    post_payload = apply_feishu_signature(
        build_brief_post_payload(brief_text, articles, report_date),
        config.feishu_secret,
    )
    try:
        logger.info("Sending Feishu post message")
        return send_feishu_webhook(config.feishu_webhook, post_payload)
    except Exception as exc:
        logger.warning("Feishu post failed, falling back to text message: %s", exc, exc_info=True)
        return send_feishu_webhook(config.feishu_webhook, text_payload)


def build_test_message() -> str:
    now = datetime.now(ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Shanghai"))).strftime("%Y-%m-%d %H:%M:%S")
    return f"每日增长情报简报测试消息发送成功。当前时间：{now}"


def run_test(config: BriefConfig) -> int:
    validate_config(config, test_mode=True)
    logger.info("Sending test message to Feishu webhook=%s", mask_secret(config.feishu_webhook))
    payload = apply_feishu_signature(build_feishu_text_payload(build_test_message()), config.feishu_secret)
    response = send_feishu_webhook(config.feishu_webhook or "", payload)
    logger.info("Feishu test send succeeded: %s", response[:200] if response else "empty response")
    return 0


def run_brief(config: BriefConfig) -> int:
    validate_config(config, test_mode=False)
    now = datetime.now(ZoneInfo(config.timezone_name))
    report_date = now.date().isoformat()
    logger.info("Daily brief started at %s", now.isoformat())
    logger.info(
        "Config feeds=%s lookback_hours=%s max_per_topic=%s webhook=%s secret=%s",
        config.feeds_path,
        config.lookback_hours,
        config.max_articles_per_topic,
        mask_secret(config.feishu_webhook),
        "set" if config.feishu_secret else "not set",
    )

    feeds = load_feeds(config.feeds_path)
    fetch_summary = fetch_and_filter(feeds, config)
    articles = assign_reference_ids(fetch_summary.articles)
    if not articles:
        raise RuntimeError("No articles found after filtering. Stop before sending an empty daily brief.")

    brief_text = generate_brief_text(articles, config, report_date)
    response = send_brief_to_feishu(config, brief_text, articles, report_date)
    logger.info("Feishu send succeeded: %s", response[:200] if response else "empty response")
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and send a Feishu daily growth intelligence brief.")
    parser.add_argument("--test", action="store_true", help="Send a Feishu test message without fetching feeds or calling LLM.")
    parser.add_argument("--text-only", action="store_true", help="Send the formal brief as a plain text Feishu message.")
    parser.add_argument("--feeds", default=None, help="Path to feeds.json.")
    parser.add_argument("--lookback-hours", type=int, default=None, help="Only keep articles from the latest N hours.")
    parser.add_argument("--max-per-topic", type=int, default=None, help="Maximum articles to keep per topic.")
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    setup_logging()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args)
        if args.test:
            return run_test(config)
        return run_brief(config)
    except BriefConfigError as exc:
        logger.error("%s", exc)
        return 2
    except Exception as exc:
        logger.exception("Daily brief failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
