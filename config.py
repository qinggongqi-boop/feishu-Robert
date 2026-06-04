from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
from typing import Any

import yaml


@dataclass(frozen=True)
class SourceConfig:
    name: str
    kind: str
    language: str
    priority: int = 0
    url: str | None = None
    query: str | None = None
    hl: str | None = None
    gl: str | None = None
    ceid: str | None = None
    enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    sources_path: Path
    db_path: Path
    timezone: str
    feishu_webhook_url: str | None
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str
    feishu_message_format: str
    max_news_items: int
    fetch_timeout_seconds: int
    fetch_retries: int
    user_agent: str


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML structure in {path}")
    return data


def load_sources(path: str | Path = "sources.yaml") -> list[SourceConfig]:
    source_path = Path(path)
    data = load_yaml(source_path)
    raw_sources = data.get("sources", [])
    if not isinstance(raw_sources, list):
        raise ValueError("sources.yaml must contain a top-level 'sources' list")

    sources: list[SourceConfig] = []
    for raw in raw_sources:
        if not isinstance(raw, dict):
            continue
        sources.append(
            SourceConfig(
                name=str(raw.get("name", "")).strip(),
                kind=str(raw.get("kind", "rss")).strip(),
                language=str(raw.get("language", "zh")).strip(),
                priority=int(raw.get("priority", 0)),
                url=raw.get("url"),
                query=raw.get("query"),
                hl=raw.get("hl"),
                gl=raw.get("gl"),
                ceid=raw.get("ceid"),
                enabled=bool(raw.get("enabled", True)),
            )
        )
    return sources


def load_app_config(
    sources_path: str | Path = "sources.yaml",
    db_path: str | Path = "data/sent_urls.sqlite3",
) -> AppConfig:
    return AppConfig(
        sources_path=Path(sources_path),
        db_path=Path(db_path),
        timezone=os.getenv("APP_TIMEZONE", "Asia/Shanghai"),
        feishu_webhook_url=os.getenv("FEISHU_WEBHOOK_URL"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        feishu_message_format=os.getenv("FEISHU_MESSAGE_FORMAT", "post"),
        max_news_items=int(os.getenv("MAX_NEWS_ITEMS", "15")),
        fetch_timeout_seconds=int(os.getenv("FETCH_TIMEOUT_SECONDS", "15")),
        fetch_retries=int(os.getenv("FETCH_RETRIES", "3")),
        user_agent=os.getenv(
            "NEWS_USER_AGENT",
            "Mozilla/5.0 (compatible; AI-News-Bot/1.0; +https://example.com/bot)",
        ),
    )
