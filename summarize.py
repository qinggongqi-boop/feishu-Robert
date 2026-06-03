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
        return description[:120].strip() or title[:120].strip()

    prompt = (
        "请基于下面的新闻标题和摘要，生成一条中文摘要。"
        "要求：1）控制在 1 到 2 句话；2）保留关键事实、公司名、产品名；"
        "3）表达自然简洁；4）不要加前缀说明。\n\n"
        f"{source_text}"
    )
    return _call_openai_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        system_prompt="You are a concise Chinese news editor.",
        user_prompt=prompt,
    )
