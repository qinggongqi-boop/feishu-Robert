from __future__ import annotations

import json
from urllib import error, request

from typing import Literal


MessageFormat = Literal["post", "card"]


def _article_block(item: dict[str, str], index: int) -> list[list[dict[str, str]]]:
    tag = item.get("tag", "新闻")
    title = item["title"]
    conclusion = item.get("conclusion", "")
    summary = item["summary"]
    source = item["source"]
    url = item["url"]
    cover = item.get("cover") or item.get("image_url", "")
    return [
        [
            {"tag": "text", "text": f"{index}. "},
            {"tag": "text", "text": f"[{tag}] ", "style": {"bold": True}},
            {"tag": "a", "text": title, "href": url},
        ],
        [{"tag": "text", "text": f"一句话结论：{conclusion}"}],
        [{"tag": "text", "text": f"中文摘要：{summary}"}],
        [{"tag": "text", "text": f"来源：{source}"}],
        [{"tag": "text", "text": f"配图：{cover}"}] if cover else [{"tag": "text", "text": "配图：无"}],
        [{"tag": "text", "text": f"原文链接：{url}"}],
    ]


def _card_article_element(item: dict[str, str], index: int) -> dict:
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
            "content": (
                f"**{index}. [{tag}] [{title}]({url})**\n"
                f"**一句话结论**：{conclusion}\n"
                f"**中文摘要**：{summary}\n"
                f"**来源**：{source}\n"
                f"**原文链接**：[打开原文]({url})"
            ),
        }
    )

    return {"tag": "div", "text": {"tag": "lark_md", "content": ""}, "fields": [], "elements": elements}


def build_feishu_post_payload(
    items: list[dict[str, str]],
    title: str,
    total_count: int,
    selected_count: int,
) -> dict:
    content: list[list[dict[str, str]]] = []
    content.append(
        [
            {"tag": "text", "text": f"共抓取 {total_count} 条新闻，精选 {selected_count} 条", "style": {"bold": True}}
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
                    "title": title,
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
) -> dict:
    elements: list[dict] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**共抓取 {total_count} 条新闻，精选 {selected_count} 条**",
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
            elements.append(_card_article_element(item, index))
            elements.append({"tag": "hr"})

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": elements,
        },
    }


def build_feishu_payload(
    items: list[dict[str, str]],
    title: str,
    total_count: int | None = None,
    selected_count: int | None = None,
    message_format: MessageFormat = "post",
) -> dict:
    total = len(items) if total_count is None else total_count
    selected = len(items) if selected_count is None else selected_count
    if message_format == "card":
        return build_feishu_card_payload(items, title=title, total_count=total, selected_count=selected)
    return build_feishu_post_payload(items, title=title, total_count=total, selected_count=selected)


def payload_to_json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def send_feishu_webhook(webhook_url: str, payload: dict) -> None:
    req = request.Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            resp.read()
    except error.HTTPError as exc:
        raise RuntimeError(f"Feishu webhook failed: {exc.read().decode('utf-8', errors='ignore')}") from exc
