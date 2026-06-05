from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sqlite3
from typing import Iterable

from fetch_news import NewsItem, canonicalize_url


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sent_urls (
    url TEXT PRIMARY KEY,
    title TEXT,
    source TEXT,
    published_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(SCHEMA_SQL)
        conn.commit()


def has_sent(db_path: str | Path, url: str) -> bool:
    path = Path(db_path)
    if not path.exists():
        return False
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT 1 FROM sent_urls WHERE url = ?", (canonicalize_url(url),)).fetchone()
        return row is not None


def mark_sent(db_path: str | Path, item: NewsItem) -> None:
    mark_sent_url(
        db_path,
        url=item.url,
        title=item.title,
        source=item.source,
        published_at=item.published_at,
    )


def mark_sent_url(db_path: str | Path, url: str, title: str = "", source: str = "", published_at: str = "") -> None:
    init_db(db_path)
    normalized_url = canonicalize_url(url)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO sent_urls (url, title, source, published_at)
            VALUES (?, ?, ?, ?)
            """,
            (normalized_url, title, source, published_at),
        )
        conn.commit()


def filter_unsent(db_path: str | Path, items: Iterable[NewsItem]) -> list[NewsItem]:
    init_db(db_path)
    unsent: list[NewsItem] = []
    seen_urls: set[str] = set()
    for item in items:
        if not item.url:
            continue
        url = canonicalize_url(item.url)
        if url in seen_urls:
            continue
        if not has_sent(db_path, url):
            unsent.append(item)
            seen_urls.add(url)
    return unsent
