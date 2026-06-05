from __future__ import annotations

from translate import _call_openai_chat


def summarize_to_zh(
    title: str,
    description: str,
    api_key: str | None,
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4.1-mini",
) -> str:
    source_text = "\n".join(part for part in [title.strip(), description.strip()] if part)
    if not source_text:
        return ""
    if not api_key:
        return (description or title)[:300].strip()

    prompt = (
        "请基于下面的新闻标题和摘要，生成一段中文新闻概述。"
        "要求：1）控制在 200 到 300 个中文字符左右，不要机械凑字数；"
        "2）保留关键事实、公司名、产品名、影响和背景；"
        "3）如果原文信息有限，可以自然说明这条新闻值得关注的原因；"
        "4）表达像中文科技媒体编辑，不要加“摘要：”等前缀。\n\n"
        f"{source_text}"
    )
    return _call_openai_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        system_prompt="You are a concise Chinese news editor.",
        user_prompt=prompt,
    )
