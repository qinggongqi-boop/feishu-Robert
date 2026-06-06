from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests


logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 3 * 1024 * 1024
SUPPORTED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _safe_slug(value: str, max_length: int = 36) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return (slug or "image")[:max_length]


def _extension_from_response(url: str, content_type: str) -> str:
    content_type = content_type.split(";", 1)[0].strip().lower()
    if content_type in SUPPORTED_IMAGE_TYPES:
        return SUPPORTED_IMAGE_TYPES[content_type]
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ""


def _looks_like_image(content: bytes, extension: str) -> bool:
    if extension == ".jpg":
        return content.startswith(b"\xff\xd8\xff")
    if extension == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if extension == ".webp":
        return content.startswith(b"RIFF") and b"WEBP" in content[:16]
    if extension == ".gif":
        return content.startswith((b"GIF87a", b"GIF89a"))
    return False


def download_image(
    url: str,
    output_dir: Path,
    filename_prefix: str,
    timeout_seconds: int,
    retries: int,
    user_agent: str,
) -> str:
    """Download one public image and return a path relative to the report page."""
    if not url or not url.startswith(("http://", "https://")):
        return ""
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": user_agent,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=headers, timeout=timeout_seconds, stream=True)
            response.raise_for_status()
            extension = _extension_from_response(url, response.headers.get("Content-Type", ""))
            if not extension:
                return ""
            content = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > MAX_IMAGE_BYTES:
                    logger.info("Image skipped because it is too large: %s", url)
                    return ""
            image_bytes = bytes(content)
            if not _looks_like_image(image_bytes, extension):
                return ""
            digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
            filename = f"{_safe_slug(filename_prefix)}-{digest}{extension}"
            local_path = output_dir / filename
            local_path.write_bytes(image_bytes)
            return f"./assets/images/{output_dir.name}/{filename}"
        except Exception as exc:
            last_error = exc
            if attempt == retries:
                break
    if last_error:
        logger.info("Image download failed for %s: %s", url, last_error)
    return ""


def localize_report_images(
    items: list[dict],
    output_dir: Path,
    target_date: str,
    timeout_seconds: int,
    retries: int,
    user_agent: str,
    max_images_per_item: int = 1,
) -> int:
    """Save report images under docs/assets/images/YYYY-MM-DD and rewrite item URLs."""
    image_dir = output_dir / "assets" / "images" / target_date
    localized_count = 0
    for index, item in enumerate(items, start=1):
        candidates = item.get("image_urls") or []
        if isinstance(candidates, str):
            candidates = [candidates]
        for key in ("cover", "image_url"):
            value = item.get(key)
            if value:
                candidates.append(value)

        local_images: list[str] = []
        for image_url in candidates:
            if len(local_images) >= max_images_per_item:
                break
            if not image_url or image_url in local_images:
                continue
            local_url = download_image(
                str(image_url),
                output_dir=image_dir,
                filename_prefix=f"{index:02d}",
                timeout_seconds=timeout_seconds,
                retries=retries,
                user_agent=user_agent,
            )
            if local_url:
                local_images.append(local_url)

        if local_images:
            item["image_urls"] = local_images
            item["image_url"] = local_images[0]
            item["cover"] = local_images[0]
            localized_count += len(local_images)
        else:
            item["image_urls"] = []
            item["image_url"] = ""
            item["cover"] = ""
    return localized_count


def cleanup_old_image_dirs(output_dir: Path, target_date: str, keep_days: int) -> None:
    try:
        cutoff = datetime.fromisoformat(target_date).date() - timedelta(days=keep_days - 1)
    except ValueError:
        return
    image_root = output_dir / "assets" / "images"
    if not image_root.exists():
        return
    for path in image_root.iterdir():
        if not path.is_dir():
            continue
        try:
            image_date = datetime.fromisoformat(path.name).date()
        except ValueError:
            continue
        if image_date < cutoff:
            for child in path.glob("*"):
                if child.is_file():
                    child.unlink()
            path.rmdir()
