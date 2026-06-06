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
        "请把下面的新闻材料改写成中文科技简报。"
        "只输出 2 到 3 句，总长 120 到 180 个中文字符。"
        "必须说清楚：发生了什么、为什么重要、后续看什么。"
        "不要照搬原文，不要添加“据报道/摘要/这条新闻”等套话，不要写空泛判断。"
        "如果材料里混有导航、广告、订阅、版权或无关菜单，请忽略。"
        "如果信息不足，只基于标题和可确认事实做简洁说明。\n\n"
        f"{source_text}"
    )
    return _call_openai_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        system_prompt="You are a concise Chinese news editor.",
        user_prompt=prompt,
    )
