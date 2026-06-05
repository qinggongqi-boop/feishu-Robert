from __future__ import annotations

from dataclasses import dataclass, asdict
import calendar
import html
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import feedparser
import requests

from config import SourceConfig


logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    language: str
    source_priority: int
    image_url: str
    published_at: str
    published_date: str
    summary: str
    raw_title: str
    raw_summary: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


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


def build_google_news_url(query: str, hl: str = "zh-CN", gl: str = "CN", ceid: str = "CN:zh-Hans") -> str:
    base = "https://news.google.com/rss/search"
    params = {"q": query, "hl": hl, "gl": gl, "ceid": ceid}
    return f"{base}?{urlencode(params)}"


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in TRACKING_PARAMS]
    rebuilt = parsed._replace(query=urlencode(query), fragment="")
    return urlunparse(rebuilt)


def _parse_datetime(entry: dict, tz: ZoneInfo) -> datetime | None:
    for key in ("published", "updated"):
        value = entry.get(key)
        if value:
            try:
                dt = parsedate_to_datetime(value)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=ZoneInfo("UTC"))
                return dt.astimezone(tz)
            except Exception:
                pass

    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            try:
                dt = datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
                return dt.astimezone(tz)
            except Exception:
                pass
    return None


def _parse_summary(entry: dict) -> str:
    summary = entry.get("summary") or entry.get("description") or ""
    if isinstance(summary, str):
        text = summary
    else:
        text = str(summary)
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _entry_url(entry: dict) -> str:
    for key in ("link", "id", "guid"):
        value = entry.get(key)
        if value:
            return canonicalize_url(str(value))
    return ""


def _entry_image_url(entry: dict) -> str:
    for key in ("media_thumbnail", "media_content", "enclosures"):
        value = entry.get(key)
        if not value:
            continue
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    url = item.get("url") or item.get("href")
                    if url:
                        return canonicalize_url(str(url))
        elif isinstance(value, dict):
            url = value.get("url") or value.get("href")
            if url:
                return canonicalize_url(str(url))
    image = entry.get("image")
    if isinstance(image, dict):
        url = image.get("href") or image.get("url")
        if url:
            return canonicalize_url(str(url))
    return ""


def is_google_news_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.endswith("news.google.com") and "/articles/" in parsed.path


def is_google_news_placeholder_image(url: str) -> bool:
    parsed = urlparse(url)
    if not parsed.netloc.endswith("googleusercontent.com"):
        return False
    return "J6_coFbogxhRI9iM864NL_liGXvsQp2AupsKei7z0cNNfDvGUmWUy20nuUhkREQyrpY4bEeIBuc" in parsed.path


def _extract_google_news_article_params(html_text: str) -> tuple[str, str, str] | None:
    article_id_match = re.search(r'data-n-a-id="([^"]+)"', html_text)
    timestamp_match = re.search(r'data-n-a-ts="([^"]+)"', html_text)
    signature_match = re.search(r'data-n-a-sg="([^"]+)"', html_text)
    if not article_id_match or not timestamp_match or not signature_match:
        return None
    return (
        html.unescape(article_id_match.group(1)),
        html.unescape(timestamp_match.group(1)),
        html.unescape(signature_match.group(1)),
    )


def resolve_google_news_url(url: str, timeout_seconds: int, retries: int, user_agent: str) -> str:
    if not is_google_news_url(url):
        return url
    try:
        html_text = _fetch_html(url, timeout_seconds=timeout_seconds, retries=retries, user_agent=user_agent)
    except Exception:
        return url
    params = _extract_google_news_article_params(html_text)
    if not params:
        return url

    article_id, timestamp, signature = params
    try:
        timestamp_int = int(timestamp)
    except ValueError:
        return url

    request_data = [
        "garturlreq",
        [
            [
                "en-US",
                "US",
                ["FINANCE_TOP_INDICES", "WEB_TEST_1_0_0"],
                None,
                None,
                1,
                1,
                "US:en",
                None,
                180,
                None,
                None,
                None,
                None,
                None,
                0,
                None,
                None,
                [timestamp_int, 0],
            ],
            "en-US",
            "US",
            1,
            [2, 3, 4, 8],
            1,
            0,
            "655000234",
            0,
            0,
            None,
            0,
        ],
        article_id,
        timestamp_int,
        signature,
    ]
    batched_payload = [[["Fbv4je", json.dumps(request_data, separators=(",", ":")), None, "generic"]]]
    headers = {
        "User-Agent": user_agent,
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
    }
    try:
        response = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je",
            headers=headers,
            data={"f.req": json.dumps(batched_payload, separators=(",", ":"))},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except Exception:
        return url

    match = re.search(r'\[\\"garturlres\\",\\"(https?://[^"\\]+)', response.text)
    if not match:
        match = re.search(r'\["garturlres","(https?://[^"\\]+)', response.text)
    if not match:
        return url
    return canonicalize_url(html.unescape(match.group(1)))


def _fetch_html(url: str, timeout_seconds: int, retries: int, user_agent: str) -> str:
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_error = exc
            if attempt == retries:
                break
    assert last_error is not None
    raise last_error


def _extract_image_from_html(html_text: str) -> str:
    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:image(?:\:src)?["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']twitter:image(?:\:src)?["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if match:
            return canonicalize_url(html.unescape(match.group(1).strip()))
    return ""


def scrape_article_image(url: str, timeout_seconds: int, retries: int, user_agent: str) -> str:
    if not url:
        return ""
    try:
        html_text = _fetch_html(url, timeout_seconds=timeout_seconds, retries=retries, user_agent=user_agent)
    except Exception:
        return ""
    return _extract_image_from_html(html_text)


def _normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_similarity(title_a: str, title_b: str) -> float:
    from difflib import SequenceMatcher

    norm_a = _normalize_title(title_a)
    norm_b = _normalize_title(title_b)
    if not norm_a or not norm_b:
        return 0.0
    return SequenceMatcher(None, norm_a, norm_b).ratio()


def dedupe_by_title_similarity(items: list[NewsItem], threshold: float = 0.85) -> list[NewsItem]:
    kept: list[NewsItem] = []
    for item in items:
        if any(title_similarity(item.title, kept_item.title) >= threshold for kept_item in kept):
            continue
        kept.append(item)
    return kept


def _fetch_feed_bytes(url: str, timeout_seconds: int, retries: int, user_agent: str) -> bytes:
    headers = {"User-Agent": user_agent, "Accept": "application/rss+xml, application/xml, text/xml, */*"}
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout_seconds)
            response.raise_for_status()
            return response.content
        except Exception as exc:
            last_error = exc
            if attempt == retries:
                break
    assert last_error is not None
    raise last_error


def fetch_source_news(
    source: SourceConfig,
    tz_name: str,
    timeout_seconds: int = 15,
    retries: int = 3,
    user_agent: str = "Mozilla/5.0 (compatible; AI-News-Bot/1.0; +https://example.com/bot)",
) -> list[NewsItem]:
    if not source.enabled:
        return []

    tz = ZoneInfo(tz_name)
    if source.kind == "google_news":
        if not source.query:
            raise ValueError(f"Google News source '{source.name}' is missing query")
        default_hl = "zh-CN" if source.language == "zh" else "en-US"
        default_gl = "CN" if source.language == "zh" else "US"
        default_ceid = "CN:zh-Hans" if source.language == "zh" else "US:en"
        url = build_google_news_url(
            source.query,
            hl=source.hl or default_hl,
            gl=source.gl or default_gl,
            ceid=source.ceid or default_ceid,
        )
    elif source.url:
        url = source.url
    else:
        raise ValueError(f"Source '{source.name}' must define url or query")

    feed_bytes = _fetch_feed_bytes(url, timeout_seconds=timeout_seconds, retries=retries, user_agent=user_agent)
    feed = feedparser.parse(feed_bytes)
    items: list[NewsItem] = []
    for entry in feed.entries:
        published_at = _parse_datetime(entry, tz)
        if not published_at:
            continue
        article_url = _entry_url(entry)
        image_url = _entry_image_url(entry)
        source_name = source.name
        if source.kind == "google_news" and isinstance(entry.get("source"), dict):
            source_name = str(entry["source"].get("title") or source.name).strip()
        items.append(
            NewsItem(
                title=str(entry.get("title", "")).strip(),
                url=article_url,
                source=source_name,
                language=source.language,
                source_priority=source.priority,
                image_url=image_url,
                published_at=published_at.isoformat(),
                published_date=published_at.date().isoformat(),
                summary=_parse_summary(entry),
                raw_title=str(entry.get("title", "")).strip(),
                raw_summary=_parse_summary(entry),
            )
        )
    return items


@dataclass
class FetchResult:
    items: list[NewsItem]
    failed_sources: list[str]
    per_source_counts: dict[str, int]


def fetch_all_news(
    sources: list[SourceConfig],
    tz_name: str,
    timeout_seconds: int = 15,
    retries: int = 3,
    user_agent: str = "Mozilla/5.0 (compatible; AI-News-Bot/1.0; +https://example.com/bot)",
) -> FetchResult:
    all_items: list[NewsItem] = []
    failed_sources: list[str] = []
    per_source_counts: dict[str, int] = {}
    for source in sources:
        try:
            items = fetch_source_news(
                source,
                tz_name,
                timeout_seconds=timeout_seconds,
                retries=retries,
                user_agent=user_agent,
            )
            all_items.extend(items)
            per_source_counts[source.name] = len(items)
        except Exception as exc:
            failed_sources.append(source.name)
            per_source_counts[source.name] = 0
            logger.exception("Failed to fetch source %s: %s", source.name, exc)
    all_items.sort(key=lambda item: (item.source_priority, item.published_at), reverse=True)
    return FetchResult(items=all_items, failed_sources=failed_sources, per_source_counts=per_source_counts)


def filter_items_by_date(items: list[NewsItem], target_date: str) -> list[NewsItem]:
    return [item for item in items if item.published_date == target_date]


def dump_items(items: list[NewsItem]) -> str:
    return json.dumps([item.to_dict() for item in items], ensure_ascii=False, indent=2)
