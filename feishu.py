from __future__ import annotations

import json
import mimetypes
from urllib import error, request
from urllib.parse import urlparse

from typing import Literal

import requests


MessageFormat = Literal["post", "card"]
DEFAULT_FEISHU_KEYWORD = "AI news 今日"


class FeishuWebhookError(RuntimeError):
    def __init__(self, message: str, response_body: str = "") -> None:
        super().__init__(message)
        self.response_body = response_body


def is_keyword_validation_error(exc: Exception) -> bool:
    body = getattr(exc, "response_body", "")
    return "Key Words Not Found" in body or '"code":19024' in body


def build_feishu_text_payload(text: str) -> dict:
    return {
        "msg_type": "text",
        "content": {
            "text": text,
        },
    }


def _title_with_keyword(title: str, keyword: str) -> str:
    return title if keyword and keyword in title else f"{keyword}｜{title}"


def build_feishu_text_digest_payload(items: list[dict[str, str]], title: str, keyword: str = DEFAULT_FEISHU_KEYWORD) -> dict:
    lines = [_title_with_keyword(title, keyword)]
    if not items:
        lines.append("今天没有筛选到符合条件的新闻。")
    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                f"{index}. [{item.get('tag', '新闻')}] {item['title']}",
                f"一句话结论：{item.get('conclusion', '')}",
                f"中文摘要：{item.get('summary', '')}",
                f"来源：{item.get('source', '')}",
                f"原文链接：{item.get('url', '')}",
                "",
            ]
        )
    return build_feishu_text_payload("\n".join(lines).strip())


def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    payload = {"app_id": app_id, "app_secret": app_secret}
    req = request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise RuntimeError(f"Feishu token request failed: {exc.read().decode('utf-8', errors='ignore')}") from exc

    if body.get("code") != 0:
        raise RuntimeError(f"Feishu token request rejected: {body}")
    token = body.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"Feishu token response missing tenant_access_token: {body}")
    return str(token)


def _guess_image_filename(image_url: str, content_type: str) -> str:
    suffix = mimetypes.guess_extension(content_type.split(";")[0].strip()) if content_type else None
    parsed_name = urlparse(image_url).path.rsplit("/", 1)[-1]
    if parsed_name and "." in parsed_name:
        return parsed_name[:80]
    return f"news-cover{suffix or '.jpg'}"


def upload_feishu_image(
    image_url: str,
    tenant_access_token: str,
    timeout_seconds: int = 15,
    user_agent: str = "Mozilla/5.0 (compatible; AI-News-Bot/1.0)",
) -> str:
    response = requests.get(image_url, headers={"User-Agent": user_agent}, timeout=timeout_seconds)
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "image/jpeg")
    if not content_type.startswith("image/"):
        raise RuntimeError(f"URL did not return an image: {content_type}")

    files = {
        "image": (
            _guess_image_filename(image_url, content_type),
            response.content,
            content_type,
        )
    }
    data = {"image_type": "message"}
    upload_resp = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/images",
        headers={"Authorization": f"Bearer {tenant_access_token}"},
        data=data,
        files=files,
        timeout=timeout_seconds,
    )
    upload_body = upload_resp.text
    upload_resp.raise_for_status()
    parsed = upload_resp.json()
    if parsed.get("code") != 0:
        raise RuntimeError(f"Feishu image upload rejected: {upload_body}")
    image_key = (parsed.get("data") or {}).get("image_key")
    if not image_key:
        raise RuntimeError(f"Feishu image upload missing image_key: {upload_body}")
    return str(image_key)


def _article_block(item: dict[str, str], index: int) -> list[list[dict[str, str]]]:
    tag = item.get("tag", "新闻")
    title = item["title"]
    conclusion = item.get("conclusion", "")
    summary = item["summary"]
    source = item["source"]
    url = item["url"]
    cover = item.get("cover") or item.get("image_url", "")
    blocks = [
        [
            {"tag": "text", "text": f"{index}. "},
            {"tag": "text", "text": f"[{tag}] ", "style": {"bold": True}},
            {"tag": "a", "text": title, "href": url},
        ],
        [{"tag": "text", "text": f"一句话结论：{conclusion}"}],
        [{"tag": "text", "text": f"中文摘要：{summary}"}],
        [{"tag": "text", "text": f"来源：{source}"}],
        [{"tag": "text", "text": "配图："}, {"tag": "a", "text": "查看配图", "href": cover}]
        if cover
        else [{"tag": "text", "text": "配图：无"}],
        [{"tag": "text", "text": "原文链接："}, {"tag": "a", "text": "打开原文", "href": url}],
    ]
    return blocks


def _card_article_elements(item: dict[str, str], index: int) -> list[dict]:
    tag = item.get("tag", "新闻")
    title = item["title"]
    conclusion = item.get("conclusion", "")
    summary = item["summary"]
    source = item["source"]
    url = item["url"]
    cover = item.get("cover") or item.get("image_url", "")
    image_key = item.get("image_key", "")

    elements: list[dict] = []
    if image_key:
        elements.append(
            {
                "tag": "img",
                "img_key": image_key,
                "alt": {"tag": "plain_text", "content": title},
                "mode": "fit_horizontal",
                "preview": True,
            }
        )
    elif cover:
        elements.append({"tag": "markdown", "content": f"**配图**：[查看封面图]({cover})"})

    elements.append(
        {
            "tag": "markdown",
            "content": f"**{index}. [{tag}] [{title}]({url})**",
        }
    )
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**一句话结论**：{conclusion}"}})
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**中文摘要**：{summary}"}})
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**来源**：{source}"}})
    elements.append({"tag": "markdown", "content": f"**原文链接**：[打开原文]({url})"})

    return elements


def build_feishu_post_payload(
    items: list[dict[str, str]],
    title: str,
    total_count: int,
    selected_count: int,
    keyword: str = DEFAULT_FEISHU_KEYWORD,
) -> dict:
    content: list[list[dict[str, str]]] = []
    content.append(
        [
            {
                "tag": "text",
                "text": f"{keyword}｜共抓取 {total_count} 条新闻，精选 {selected_count} 条",
                "style": {"bold": True},
            }
        ]
    )
    content.append([{"tag": "text", "text": ""}])
    if not items:
        content.append([{"tag": "text", "text": "今天没有筛选到符合条件的新闻。"}])
    else:
        for index, item in enumerate(items, start=1):
            content.extend(_article_block(item, index))
            content.append([{"tag": "text", "text": ""}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": _title_with_keyword(title, keyword),
                    "content": content,
                }
            }
        },
    }


def build_feishu_card_payload(
    items: list[dict[str, str]],
    title: str,
    total_count: int,
    selected_count: int,
    keyword: str = DEFAULT_FEISHU_KEYWORD,
) -> dict:
    elements: list[dict] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{keyword}｜共抓取 {total_count} 条新闻，精选 {selected_count} 条**",
            },
        },
        {"tag": "hr"},
    ]

    if not items:
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": "今天没有筛选到符合条件的新闻。"},
            }
        )
    else:
        for index, item in enumerate(items, start=1):
            elements.extend(_card_article_elements(item, index))
            elements.append({"tag": "hr"})

    return {
        "msg_type": "interactive",
        "card": {
            "schema": "2.0",
            "config": {
                "wide_screen_mode": True,
                "update_multi": True,
            },
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": _title_with_keyword(title, keyword)},
            },
            "body": {
                "direction": "vertical",
                "elements": elements,
            },
        },
    }


def build_feishu_payload(
    items: list[dict[str, str]],
    title: str,
    total_count: int | None = None,
    selected_count: int | None = None,
    message_format: MessageFormat = "post",
    keyword: str = DEFAULT_FEISHU_KEYWORD,
) -> dict:
    total = len(items) if total_count is None else total_count
    selected = len(items) if selected_count is None else selected_count
    if message_format == "card":
        return build_feishu_card_payload(
            items,
            title=title,
            total_count=total,
            selected_count=selected,
            keyword=keyword,
        )
    return build_feishu_post_payload(
        items,
        title=title,
        total_count=total,
        selected_count=selected,
        keyword=keyword,
    )


def payload_to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def send_feishu_webhook(webhook_url: str, payload: dict) -> str:
    req = request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
    except error.HTTPError as exc:
        raise RuntimeError(f"Feishu webhook failed: {exc.read().decode('utf-8', errors='ignore')}") from exc
    except Exception as exc:
        raise RuntimeError(f"Feishu webhook request failed: {exc}") from exc

    if body:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return body
        if isinstance(data, dict):
            code = data.get("code")
            if isinstance(code, int) and code != 0:
                raise FeishuWebhookError(f"Feishu webhook rejected payload: {body}", response_body=body)
            status_code = data.get("StatusCode")
            if isinstance(status_code, int) and status_code != 0:
                raise FeishuWebhookError(f"Feishu webhook rejected payload: {body}", response_body=body)
    return body
