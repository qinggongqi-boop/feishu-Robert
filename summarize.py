from __future__ import annotations

import re
import time

from translate import _call_openai_chat


def clean_model_summary(text: str) -> str:
    summary = " ".join((text or "").split())
    summary = re.sub(r"^(摘要|概述|新闻概述|简报|总结)[:：]\s*", "", summary)
    summary = summary.replace("发生了什么：", "").replace("为什么重要：", "").replace("后续看点：", "")
    summary = re.sub(r"\s*([，。！？；：、])\s*", r"\1", summary)
    summary = re.sub(r"([。！？]){2,}", r"\1", summary).strip()
    if summary and not summary.endswith(("。", "！", "？")):
        summary += "。"
    return summary


def summarize_to_zh(
    title: str,
    description: str,
    api_key: str | None,
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4.1-mini",
    retries: int = 1,
    timeout_seconds: int = 20,
) -> str:
    source_text = "\n".join(part for part in [title.strip(), description.strip()] if part)
    if not source_text:
        return ""
    if not api_key:
        return clean_model_summary((description or title)[:500])

    prompt = (
        "请把下面的新闻材料改写成一段中文科技新闻概述，面向每天快速浏览 AI 新闻的读者。"
        "目标是让读者一眼看明白：谁做了什么、涉及什么产品/公司/政策、为什么值得关注、后续需要看什么。"
        "要求："
        "1）只输出自然中文段落，不要小标题、编号、Markdown、项目符号；"
        "2）长度控制在 100 到 500 个中文字符，信息足够时优先 180 到 350 字；"
        "3）第一句必须交代清楚新闻主体和动作，例如发布、融资、监管、收购、合作、涨价、开源、下架、调查；"
        "4）第二部分说明关键背景或影响，尽量保留公司名、产品名、数字、时间、地区、对象；"
        "5）最后自然带出后续看点，例如落地效果、价格、监管风险、生态跟进、竞争影响；"
        "6）不要写“意义重大、值得关注、引发热议”等空泛套话，除非说明具体原因；"
        "7）如果材料混有导航、广告、订阅、版权、推荐文章，请忽略；"
        "8）如果公开信息不足，要明确写“目前公开信息有限”，不要编造事实。\n\n"
        f"{source_text}"
    )
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return clean_model_summary(_call_openai_chat(
                api_key=api_key,
                base_url=base_url,
                model=model,
                system_prompt=(
                    "You are a careful Chinese technology news editor. "
                    "Write clear, factual, information-dense Chinese summaries. "
                    "Do not invent facts."
                ),
                user_prompt=prompt,
                timeout_seconds=timeout_seconds,
            ))
        except RuntimeError as exc:
            last_error = exc
            if "HTTP 503" not in str(exc) or attempt >= retries:
                break
            time.sleep(2)
    if last_error:
        raise last_error
    return ""
