from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config import load_app_config, load_sources
from dedupe import filter_unsent, mark_sent, mark_sent_url
from fetch_news import (
    ArticleMetadata,
    dedupe_by_title_similarity,
    fetch_all_news,
    filter_items_by_date,
    is_google_news_placeholder_image,
    is_google_news_url,
    resolve_google_news_url,
    scrape_article_metadata,
)
from images import cleanup_old_image_dirs, localize_report_images
from feishu import (
    build_feishu_text_payload,
    payload_to_json,
    send_feishu_webhook,
)
from report import write_report
from summarize import summarize_to_zh
from translate import translate_to_zh_stable, translate_to_zh_with_base_url


logger = logging.getLogger(__name__)
DOMESTIC_MIN_ITEMS = 4
OVERSEAS_MIN_ITEMS = 6
QUALITY_CANDIDATE_MULTIPLIER = 5
MOJIBAKE_CHARS = set("�ÃÂåæçðø¢£¤¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º¼½¾¿ÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞß")
LOW_QUALITY_SOURCES = {
    "moomoo",
    "vocal.media",
    "the tech buzz",
    "trt world",
    "aibase",
}
SUMMARY_NOISE_MARKERS = {
    "口座開設",
    "入金 出金",
    "米国株現物取引",
    "銘柄スクリーナー",
    "TechBuzz Press",
    "110 万订阅者",
    "110万订阅者",
    "The Daily Brief",
    "latest technology updates sent directly",
    "Home Top Stories",
    "Main navigation",
    "Newsletter",
    "Subscribe",
}
SUMMARY_SIGNAL_TERMS = {
    "AI",
    "人工智能",
    "模型",
    "大模型",
    "生成式",
    "智能体",
    "芯片",
    "半导体",
    "GPU",
    "数据中心",
    "云",
    "发布",
    "推出",
    "升级",
    "开源",
    "监管",
    "安全",
    "政策",
    "融资",
    "投资",
    "收购",
    "营收",
    "用户",
    "开发者",
    "企业",
    "OpenAI",
    "Anthropic",
    "Google",
    "DeepMind",
    "Microsoft",
    "Meta",
    "Nvidia",
    "英伟达",
    "阿里",
    "腾讯",
    "百度",
    "字节",
    "华为",
}
SUMMARY_ACTION_TERMS = {
    "宣布",
    "发布",
    "推出",
    "提升",
    "支持",
    "用于",
    "上线",
    "开放",
    "升级",
    "开源",
    "融资",
    "投资",
    "收购",
    "合作",
    "调查",
    "监管",
    "起诉",
    "禁止",
    "计划",
    "测试",
    "部署",
    "应用",
    "裁员",
    "招聘",
    "涨价",
    "降价",
}
SUMMARY_IMPACT_TERMS = {
    "影响",
    "意味着",
    "企业",
    "开发者",
    "用户",
    "监管",
    "安全",
    "成本",
    "价格",
    "竞争",
    "生态",
    "落地",
    "商业化",
    "风险",
    "后续",
}


def looks_mostly_english(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    ascii_letters = [char for char in letters if char.isascii()]
    return len(ascii_letters) / len(letters) > 0.72


def looks_mojibake(text: str) -> bool:
    clean_text = text or ""
    if not clean_text.strip():
        return False
    if "?" * 8 in clean_text:
        return True
    visible_chars = [char for char in clean_text if not char.isspace()]
    if not visible_chars:
        return False
    mojibake_count = sum(1 for char in visible_chars if char in MOJIBAKE_CHARS)
    if mojibake_count >= 6 and mojibake_count / len(visible_chars) > 0.06:
        return True
    odd_sequences = re.findall(r"(?:å|æ|ç|Ã|Â|Ð|Ø|º|¼|½|¾|®|¶|¥).{0,3}", clean_text)
    return len(odd_sequences) >= 5


def is_content_quality_ok(title: str, summary: str, original_title: str = "", min_summary_chars: int = 80) -> bool:
    if looks_mojibake(title) or looks_mojibake(summary):
        return False
    if has_noise_markers(summary):
        return False
    if looks_mostly_english(title):
        return False
    if len("".join(summary.split())) < min_summary_chars:
        return False
    if original_title and title.strip() == original_title.strip() and looks_mostly_english(original_title):
        return False
    if not is_summary_explanatory(f"{title}。{summary}", min_chars=min_summary_chars):
        return False
    return True


def is_summary_explanatory(summary: str, min_chars: int = 80) -> bool:
    clean_summary = " ".join((summary or "").split())
    if len(clean_summary) < min_chars:
        return False
    if looks_mostly_english(clean_summary) or looks_mojibake(clean_summary) or has_noise_markers(clean_summary):
        return False
    has_subject = any(term.lower() in clean_summary.lower() for term in SUMMARY_SIGNAL_TERMS)
    has_action = any(term in clean_summary for term in SUMMARY_ACTION_TERMS)
    has_impact = any(term in clean_summary for term in SUMMARY_IMPACT_TERMS)
    empty_phrases = (
        "值得关注相关公司是否披露更多",
        "反映出 AI 技术正在",
        "这条新闻的重点不只在单个事件本身",
        "建议结合原文进一步查看",
    )
    if any(phrase in clean_summary for phrase in empty_phrases):
        return False
    return has_subject and has_action and has_impact


def is_raw_item_quality_ok(item) -> bool:
    raw_text = " ".join([item.title or "", item.summary or "", item.raw_summary or ""])
    if is_low_quality_source(item.source):
        return False
    return not looks_mojibake(raw_text) and not has_noise_markers(raw_text)


def is_low_quality_source(source: str) -> bool:
    source_lower = (source or "").lower()
    return any(marker in source_lower for marker in LOW_QUALITY_SOURCES)


def has_noise_markers(text: str) -> bool:
    clean_text = text or ""
    return any(marker.lower() in clean_text.lower() for marker in SUMMARY_NOISE_MARKERS)


TERM_TRANSLATIONS = [
    (r"\bagentic AI\b", "智能体 AI"),
    (r"\bartificial intelligence\b", "人工智能"),
    (r"\bgenerative AI\b", "生成式 AI"),
    (r"\blarge language models?\b", "大语言模型"),
    (r"\bAI models?\b", "AI 模型"),
    (r"\bAI systems?\b", "AI 系统"),
    (r"\bAI skills?\b", "AI 技能"),
    (r"\bAI lab\b", "AI 实验室"),
    (r"\bAI practices?\b", "AI 做法"),
    (r"\bdata centers?\b", "数据中心"),
    (r"\bcloud\b", "云计算"),
    (r"\bchips?\b", "芯片"),
    (r"\bsemiconductors?\b", "半导体"),
    (r"\bregulation\b", "监管"),
    (r"\bsafety\b", "安全"),
    (r"\bpolicy\b", "政策"),
    (r"\bpropaganda\b", "宣传操纵"),
    (r"\breal-world operations?\b", "真实业务运营"),
    (r"\bhuman-centered\b", "以人为中心"),
    (r"\bhealth capabilities?\b", "健康能力"),
    (r"\bbiological weapon\b", "生物武器"),
    (r"\bDNA screening\b", "DNA 筛查"),
    (r"\btask management\b", "任务管理"),
    (r"\bfraud detection\b", "欺诈检测"),
    (r"\bcompetition probe\b", "竞争调查"),
    (r"\bpremium salaries\b", "高薪溢价"),
    (r"\bstartup\b", "创业公司"),
    (r"\bstartups\b", "创业公司"),
    (r"\bCEO\b", "CEO"),
    (r"\bAGI\b", "通用人工智能"),
    (r"\bASI\b", "超级人工智能"),
    (r"\bSoftBank\b", "软银"),
    (r"\bMasayoshi Son\b", "孙正义"),
    (r"\bSon\b", "孙正义"),
    (r"\bOpenAI's\b", "OpenAI 的"),
]


def strip_source_suffix(title: str) -> str:
    return re.sub(r"\s+-\s+[^-]{2,80}$", "", title).strip()


def strip_chinese_source_suffix(title: str) -> str:
    stripped = re.sub(r"\s*[-－]\s*[^-－]{2,24}$", "", title).strip()
    return re.sub(r"\s*[·•]\s*[^·•]{2,40}$", "", stripped).strip()


def review_chinese_translation(text: str, original_text: str = "") -> str:
    reviewed = " ".join((text or "").split())
    original = original_text or ""
    if re.search(r"\b(Masayoshi Son|SoftBank|Son Revises|Son says|Son claimed)\b", original, flags=re.IGNORECASE):
        reviewed = reviewed.replace("儿子", "孙正义")
        reviewed = reviewed.replace("儿子修", "孙正义修")
        reviewed = reviewed.replace("孙正义子", "孙正义")
    replacements = {
        "代理人工智能": "智能体 AI",
        "代理 AI": "智能体 AI",
        "生成人工智能": "生成式 AI",
        "人工智能模型": "AI 模型",
        "人工智能芯片": "AI 芯片",
        "人工智能代理": "AI 智能体",
        "代理人 AI": "智能体 AI",
        "推理模型": "推理模型",
        "幻觉": "幻觉",
        "聊天GPT": "ChatGPT",
        "开放人工智能": "OpenAI",
        "开放 AI": "OpenAI",
        "人类的": "Anthropic",
        "人择": "Anthropic",
        "深度思维": "DeepMind",
        "元人工智能": "Meta AI",
        "元 AI": "Meta AI",
        "微软人工智能": "Microsoft AI",
        "英伟达公司": "英伟达",
        "黑井": "Blackwell",
        "布莱克韦尔": "Blackwell",
        "GB200": "GB200",
        "GB300": "GB300",
        "超级人工智能时间表": "ASI 时间表",
        "软银 的孙正义": "软银孙正义",
        "OpenAI 的模型": "OpenAI 模型",
        "Google 放弃": "Google 发布",
        "谷歌放弃": "谷歌发布",
        "谷歌 放弃": "谷歌发布",
        "人工智能综述": "AI 月度综述",
    }
    for bad, good in replacements.items():
        reviewed = reviewed.replace(bad, good)
    if re.search(r"(?<![A-Za-z])hack(?![A-Za-z])", original, flags=re.IGNORECASE) or re.search(
        r"(?<![A-Za-z])hack(?![A-Za-z])", reviewed, flags=re.IGNORECASE
    ):
        reviewed = re.sub(r"(?<![A-Za-z])Meta\s+hack(?![A-Za-z])", "Meta 遭黑客攻击", reviewed, flags=re.IGNORECASE)
        reviewed = re.sub(r"(?<![A-Za-z])hack(?![A-Za-z])", "黑客攻击", reviewed, flags=re.IGNORECASE)
    reviewed = re.sub(r"\s+", " ", reviewed).strip()
    return reviewed


def postprocess_chinese_text(text: str, original_text: str = "") -> str:
    """Normalize machine-translated Chinese before quality checks and report rendering."""
    reviewed = clean_summary_material(text)
    reviewed = apply_term_glossary(reviewed)
    reviewed = review_chinese_translation(reviewed, original_text)
    reviewed = reviewed.replace(" ,", "，").replace(" .", "。").replace(" ;", "；")
    reviewed = re.sub(r"\s*([，。！？；：、])\s*", r"\1", reviewed)
    reviewed = re.sub(r"([。！？]){2,}", r"\1", reviewed)
    reviewed = re.sub(r"\s+", " ", reviewed).strip()
    return reviewed


def apply_term_glossary(text: str) -> str:
    result = text
    for pattern, replacement in TERM_TRANSLATIONS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    result = result.replace("’s", " 的").replace("'s", " 的")
    result = result.replace("“", "「").replace("”", "」")
    return review_chinese_translation(" ".join(result.split()), text)


def heuristic_english_title_to_zh(title: str) -> str:
    clean_title = strip_source_suffix(title)
    normalized = apply_term_glossary(clean_title)
    patterns = [
        (r"^Study:\s*(.+)$", "研究：{0}"),
        (r"^(.+?) launches (.+?) for (.+)$", "{0}推出面向{2}的{1}"),
        (r"^(.+?) launches (.+)$", "{0}推出{1}"),
        (r"^(.+?) faces (.+?) over (.+)$", "{0}因{2}面临{1}"),
        (r"^(.+?) call for (.+)$", "{0}呼吁{1}"),
        (r"^(.+?) calls for (.+)$", "{0}呼吁{1}"),
        (r"^(.+?) may soon (.+)$", "{0}可能很快{1}"),
        (r"^(.+?) says (.+)$", "{0}表示：{1}"),
        (r"^(.+?) driving (.+)$", "{0}推动{1}"),
    ]
    for pattern, template in patterns:
        match = re.match(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return template.format(*(part.strip() for part in match.groups()))
    if re.search(r"[\u4e00-\u9fff]", normalized):
        return normalized
    return f"AI 科技动态：{normalized}"


def yesterday_in_tz(tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    yesterday = now - timedelta(days=1)
    return yesterday.date().isoformat()


def chinese_fallback_title(
    title: str,
    azure_translator_key: str | None = None,
    azure_translator_region: str | None = None,
    volcengine_access_key_id: str | None = None,
    volcengine_secret_access_key: str | None = None,
    volcengine_region: str = "cn-north-1",
) -> str:
    translated = translate_to_zh_stable(title, azure_key=azure_translator_key, azure_region=azure_translator_region, volcengine_access_key_id=volcengine_access_key_id, volcengine_secret_access_key=volcengine_secret_access_key, volcengine_region=volcengine_region)
    if translated and translated != title:
        return review_chinese_translation(strip_chinese_source_suffix(translated), title)
    return review_chinese_translation(heuristic_english_title_to_zh(title), title)


def chinese_fallback_summary(
    summary: str,
    title: str,
    source: str,
    azure_translator_key: str | None = None,
    azure_translator_region: str | None = None,
    volcengine_access_key_id: str | None = None,
    volcengine_secret_access_key: str | None = None,
    volcengine_region: str = "cn-north-1",
) -> str:
    source_text = " ".join((summary or title).split())
    if not source_text:
        return f"这篇来自 {source} 的报道涉及 AI 或科技行业的重要动态，建议结合原文进一步查看事件细节、相关公司表态以及后续影响。"
    translated = translate_to_zh_stable(source_text, azure_key=azure_translator_key, azure_region=azure_translator_region, volcengine_access_key_id=volcengine_access_key_id, volcengine_secret_access_key=volcengine_secret_access_key, volcengine_region=volcengine_region)
    clean_text = translated if translated and translated != source_text else apply_term_glossary(source_text)
    clean_text = clean_summary_material(clean_text)
    clean_text = review_chinese_translation(clean_text, source_text)
    clean_text = compact_editorial_summary(clean_text)
    if not clean_text:
        return ""
    return clean_text


def clean_summary_material(text: str) -> str:
    noise_patterns = [
        r"\bBNN News BNN\b.*?(?=研究|人工智能|AI|据|这)",
        r"\bMain navigation\b.*?(?=\d|AI|Artificial|The|人工智能)",
        r"\bHome Top Stories Latest Stories\b",
        r"\bAdvertisement\b",
        r"\bFacebook Twitter\b",
        r"\bSearch Home\b",
        r"\b2 -MIN READ\b.*?\bListen\b",
        r"主导航.*?(?=\d|人工智能|AI)",
        r"主页 热门故事 最新故事",
        r"广告 搜索",
        r"はじめての方へ.*?(?=。|$)",
        r"口座開設の流れ.*?(?=。|$)",
        r"通过 TechBuzz Press.*?(?=。|$)",
        r"《每日报》将最新技术更新直接发送到您的收件箱。?",
        r"吸引超过\s*110\s*万订阅者。?",
    ]
    cleaned = text
    for pattern in noise_patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"[?？]{4,}", " ", cleaned)
    cleaned = re.sub(r"©\s*\d{4}.*?版权所有。?", " ", cleaned)
    cleaned = re.sub(r"直播电视|政治 土耳其|信息图专题|时事通讯|文章 时事通讯", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def split_sentences(text: str) -> list[str]:
    clean_text = " ".join((text or "").split())
    if not clean_text:
        return []
    parts = re.split(r"(?<=[。！？!?])\s+|(?<=[。！？!?])|(?<=[.!?])\s+", clean_text)
    sentences: list[str] = []
    for part in parts:
        sentence = part.strip(" ，,;；")
        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", sentence))
        min_length = 8 if has_chinese else 16
        if len(sentence) < min_length:
            continue
        if has_noise_markers(sentence) or looks_mojibake(sentence):
            continue
        if sentence not in sentences:
            sentences.append(sentence)
    return sentences


def sentence_information_score(sentence: str) -> int:
    score = 0
    for term in SUMMARY_SIGNAL_TERMS:
        if term.lower() in sentence.lower():
            score += 3
    score += min(len(re.findall(r"\d+(?:\.\d+)?%?|\d+\s*(?:亿|万|美元|元|人|项|个)", sentence)), 4) * 2
    score += min(len(re.findall(r"[A-Z][A-Za-z0-9.-]{1,}|[\u4e00-\u9fff]{2,}", sentence)), 12)
    if any(word in sentence for word in ("表示", "称", "宣布", "推出", "发布", "计划", "将", "正在", "已")):
        score += 2
    if any(word in sentence for word in ("值得关注", "影响", "意味着", "可能", "后续", "竞争", "落地")):
        score += 2
    if has_noise_markers(sentence) or looks_mojibake(sentence):
        score -= 20
    if len(sentence) < 18:
        score -= 4
    return score


def compact_editorial_summary(text: str, min_chars: int = 100, max_chars: int = 500) -> str:
    clean_text = clean_summary_material(text)
    sentences = split_sentences(clean_text)
    if not sentences and len(clean_text) >= 30:
        sentences = [clean_text]
    if not sentences:
        return ""

    indexed_sentences = list(enumerate(sentences))
    selected_indexes: set[int] = set()
    if indexed_sentences:
        selected_indexes.add(0)
    ranked = sorted(
        indexed_sentences,
        key=lambda item: (sentence_information_score(item[1]), -item[0]),
        reverse=True,
    )
    current_len = sum(len(sentences[index]) for index in selected_indexes)
    for index, sentence in ranked:
        if index in selected_indexes:
            continue
        if current_len >= min_chars and len(selected_indexes) >= 3:
            break
        selected_indexes.add(index)
        current_len += len(sentence)

    selected: list[str] = []
    for index in sorted(selected_indexes):
        sentence = postprocess_chinese_text(sentences[index], clean_text).rstrip("。！？!?")
        if sentence and sentence not in selected:
            selected.append(sentence + "。")
    result = "".join(selected).strip()
    if len(result) > max_chars:
        cut = result[:max_chars].rsplit("。", 1)[0]
        result = (cut or result[:max_chars]).rstrip("，。；;,. ") + "。"
    result = postprocess_chinese_text(result, clean_text)
    if result and not result.endswith(("。", "！", "？")):
        result += "。"
    return result


def build_local_summary(
    source_text: str,
    title: str,
    source: str,
    azure_translator_key: str | None = None,
    azure_translator_region: str | None = None,
    volcengine_access_key_id: str | None = None,
    volcengine_secret_access_key: str | None = None,
    volcengine_region: str = "cn-north-1",
) -> str:
    clean_source = clean_summary_material(source_text)
    if not clean_source:
        return ""
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", clean_source))
    latin_letters = len(re.findall(r"[A-Za-z]", clean_source))
    if chinese_chars >= 30 and chinese_chars >= latin_letters / 2:
        material = clean_source[:900]
    elif not (
        (volcengine_access_key_id and volcengine_secret_access_key)
        or (azure_translator_key and azure_translator_region)
    ):
        title_summary = review_chinese_translation(title, source_text).rstrip("。；;,.，")
        if len(title_summary) >= 18:
            return (
                f"{title_summary}。由于当前未配置火山引擎或 Azure 翻译密钥，英文正文暂不做长段机器翻译，"
                "请优先点击原文查看完整细节；配置翻译密钥后会自动生成更完整的中文概述。"
            )
        return ""
    else:
        material_source = clean_source[:1200]
        translated = translate_to_zh_stable(material_source, azure_key=azure_translator_key, azure_region=azure_translator_region, volcengine_access_key_id=volcengine_access_key_id, volcengine_secret_access_key=volcengine_secret_access_key, volcengine_region=volcengine_region)
        material = translated if translated and translated != material_source else material_source
    material = postprocess_chinese_text(material, source_text)
    summary = compact_editorial_summary(material)
    if summary and not has_noise_markers(summary):
        return summary
    title_summary = review_chinese_translation(title, source_text).rstrip("。；;,.，")
    if len(title_summary) >= 18:
        return f"{title_summary}。"
    return ""


def polish_summary(
    summary: str,
    source_text: str,
    title: str,
    source: str,
    force_fallback: bool = False,
    azure_translator_key: str | None = None,
    azure_translator_region: str | None = None,
    volcengine_access_key_id: str | None = None,
    volcengine_secret_access_key: str | None = None,
    volcengine_region: str = "cn-north-1",
) -> str:
    clean_summary = " ".join((summary or "").split())
    if force_fallback or looks_mostly_english(clean_summary) or looks_mojibake(clean_summary):
        clean_summary = build_local_summary(
            source_text,
            title,
            source,
            azure_translator_key=azure_translator_key,
            azure_translator_region=azure_translator_region,
            volcengine_access_key_id=volcengine_access_key_id,
            volcengine_secret_access_key=volcengine_secret_access_key,
            volcengine_region=volcengine_region,
        )
    clean_summary = clean_summary_material(clean_summary)
    clean_summary = postprocess_chinese_text(clean_summary, source_text)
    compact = compact_editorial_summary(clean_summary)
    if compact and not has_noise_markers(compact):
        return compact
    if not clean_summary:
        return ""
    return clean_summary[:500].rstrip("，。；;,. ") + "。"


def build_summary_source(item, metadata: ArticleMetadata | None) -> str:
    parts = [
        metadata.description if metadata else "",
        metadata.text if metadata else "",
        item.summary,
        item.raw_summary,
    ]
    clean_parts: list[str] = []
    for part in parts:
        text = " ".join((part or "").split())
        text = clean_summary_material(text)
        if text and text not in clean_parts:
            clean_parts.append(text)
    if not clean_parts:
        clean_parts.append((metadata.title if metadata and metadata.title else item.title).strip())
    return "\n".join(clean_parts)[:2200]


def has_article_signal(item, metadata: ArticleMetadata | None, summary_source: str) -> bool:
    if is_low_quality_source(item.source):
        return False
    if has_noise_markers(summary_source):
        return False
    clean_source = clean_summary_material(summary_source)
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", clean_source))
    latin_words = len(re.findall(r"\b[A-Za-z][A-Za-z-]{2,}\b", clean_source))
    if chinese_chars + latin_words * 4 < 80:
        return False
    metadata_text_len = len("".join(((metadata.text if metadata else "") or "").split()))
    description_len = len("".join(((metadata.description if metadata else "") or "").split()))
    item_summary_len = len("".join((item.summary or item.raw_summary or "").split()))
    return max(metadata_text_len, description_len, item_summary_len) >= 60


def enrich_item(
    item,
    openai_api_key: str | None,
    openai_base_url: str,
    openai_model: str,
    metadata: ArticleMetadata | None = None,
    azure_translator_key: str | None = None,
    azure_translator_region: str | None = None,
    volcengine_access_key_id: str | None = None,
    volcengine_secret_access_key: str | None = None,
    volcengine_region: str = "cn-north-1",
    openai_summary_enabled: bool = False,
) -> dict[str, str]:
    original_title = (metadata.title if metadata and metadata.title else item.raw_title or item.title).strip()
    title_cn = original_title
    summary_source = build_summary_source(item, metadata)
    if not has_article_signal(item, metadata, summary_source):
        return {}
    if item.language.lower().startswith("en"):
        title_cn = translate_to_zh_stable(original_title, azure_key=azure_translator_key, azure_region=azure_translator_region, volcengine_access_key_id=volcengine_access_key_id, volcengine_secret_access_key=volcengine_secret_access_key, volcengine_region=volcengine_region)
        title_translated = title_cn != original_title and not looks_mostly_english(title_cn)
        try:
            if not title_translated:
                title_cn = translate_to_zh_with_base_url(
                    original_title,
                    openai_api_key,
                    base_url=openai_base_url,
                    model=openai_model,
                )
                title_translated = title_cn != original_title and not looks_mostly_english(title_cn)
        except Exception as exc:
            logger.warning("Title translation failed for %s: %s", item.url, exc)
        if not title_translated:
            title_cn = chinese_fallback_title(
                original_title,
                azure_translator_key,
                azure_translator_region,
                volcengine_access_key_id=volcengine_access_key_id,
                volcengine_secret_access_key=volcengine_secret_access_key,
                volcengine_region=volcengine_region,
            )
        title_cn = review_chinese_translation(strip_chinese_source_suffix(title_cn), original_title)
    summary_cn = build_local_summary(
        summary_source,
        title_cn or original_title,
        item.source,
        azure_translator_key=azure_translator_key,
        azure_translator_region=azure_translator_region,
        volcengine_access_key_id=volcengine_access_key_id,
        volcengine_secret_access_key=volcengine_secret_access_key,
        volcengine_region=volcengine_region,
    )
    summary_source_label = "本地回退"
    if openai_api_key and openai_summary_enabled:
        local_summary = summary_cn
        try:
            model_summary = summarize_to_zh(
                title_cn,
                summary_source or summary_cn or item.summary,
                openai_api_key,
                base_url=openai_base_url,
                model=openai_model,
                retries=1,
            )
            model_summary = postprocess_chinese_text(model_summary, summary_source)
            if is_summary_explanatory(f"{title_cn}。{model_summary}", min_chars=100):
                summary_cn = model_summary
                summary_source_label = "模型摘要"
            else:
                logger.info("Model summary failed quality gate for %s; using local summary", item.url)
                summary_cn = local_summary
        except Exception as exc:
            logger.warning("Summary generation failed for %s: %s", item.url, exc)
    summary_cn = polish_summary(
        summary_cn,
        source_text=summary_source,
        title=title_cn or original_title,
        source=item.source,
        force_fallback=item.language.lower().startswith("en") and looks_mostly_english(summary_cn),
        azure_translator_key=azure_translator_key,
        azure_translator_region=azure_translator_region,
        volcengine_access_key_id=volcengine_access_key_id,
        volcengine_secret_access_key=volcengine_secret_access_key,
        volcengine_region=volcengine_region,
    )
    if item.language.lower().startswith("en") and looks_mostly_english(summary_cn):
        translated_source = translate_to_zh_stable(summary_source, azure_key=azure_translator_key, azure_region=azure_translator_region, volcengine_access_key_id=volcengine_access_key_id, volcengine_secret_access_key=volcengine_secret_access_key, volcengine_region=volcengine_region)
        summary_cn = polish_summary(
            chinese_fallback_summary(
                translated_source,
                title_cn or original_title,
                item.source,
                azure_translator_key=azure_translator_key,
                azure_translator_region=azure_translator_region,
                volcengine_access_key_id=volcengine_access_key_id,
                volcengine_secret_access_key=volcengine_secret_access_key,
                volcengine_region=volcengine_region,
            ),
            source_text=translated_source,
            title=title_cn or original_title,
            source=item.source,
            force_fallback=False,
            azure_translator_key=azure_translator_key,
            azure_translator_region=azure_translator_region,
            volcengine_access_key_id=volcengine_access_key_id,
            volcengine_secret_access_key=volcengine_secret_access_key,
            volcengine_region=volcengine_region,
        )

    if not summary_cn:
        return {}
    return {
        "title": title_cn or item.title,
        "original_title": original_title,
        "url": item.url,
        "source": item.source,
        "published_at": item.published_at,
        "summary": summary_cn or chinese_fallback_summary(summary_source, title_cn or original_title, item.source),
        "summary_material": summary_source,
        "summary_source": summary_source_label,
        "image_url": item.image_url,
        "image_urls": [item.image_url] if item.image_url else [],
    }


def enhance_final_summaries_with_model(
    items: list[dict[str, str]],
    *,
    openai_api_key: str | None,
    openai_base_url: str,
    openai_summary_model: str,
) -> None:
    if not openai_api_key:
        logger.info("Model summary enhancement skipped: OPENAI_API_KEY is not set")
        return

    model_count = 0
    fallback_count = 0
    for index, item in enumerate(items):
        local_summary = item.get("summary", "")
        material = item.get("summary_material") or local_summary
        title = item.get("title") or item.get("original_title") or ""
        try:
            model_summary = summarize_to_zh(
                title,
                material,
                openai_api_key,
                base_url=openai_base_url,
                model=openai_summary_model,
                retries=1,
            )
            model_summary = postprocess_chinese_text(model_summary, material)
            if is_summary_explanatory(f"{title}。{model_summary}", min_chars=100):
                item["summary"] = model_summary
                item["summary_source"] = "模型摘要"
                model_count += 1
                continue
            logger.info("Model summary failed quality gate for %s; using local summary", item.get("url", ""))
        except Exception as exc:
            logger.warning("Summary generation failed for %s: %s", item.get("url", ""), exc)
            if "not supported" in str(exc) or "HTTP 400" in str(exc):
                for remaining_item in items[index:]:
                    remaining_item["summary_source"] = "本地回退"
                fallback_count += len(items) - index
                logger.warning(
                    "Model summary enhancement stopped because model %s is unsupported",
                    openai_summary_model,
                )
                break
        item["summary"] = local_summary
        item["summary_source"] = "本地回退"
        fallback_count += 1

    logger.info("Model summaries used: %d; local fallback summaries: %d", model_count, fallback_count)


def attach_article_metadata(items, timeout_seconds: int, retries: int, user_agent: str) -> dict[str, ArticleMetadata]:
    metadata_by_url: dict[str, ArticleMetadata] = {}
    for item in items:
        if not item.url:
            continue
        if is_google_news_url(item.url):
            resolved_url = resolve_google_news_url(
                item.url,
                timeout_seconds=timeout_seconds,
                retries=retries,
                user_agent=user_agent,
            )
            if resolved_url != item.url:
                item.url = resolved_url
        existing_image = item.image_url
        metadata = scrape_article_metadata(
            item.url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            user_agent=user_agent,
        )
        metadata_by_url[item.url] = metadata
        if metadata.image_url:
            item.image_url = metadata.image_url
        elif existing_image and not is_google_news_placeholder_image(existing_image):
            item.image_url = existing_image
        else:
            item.image_url = ""
    return metadata_by_url


def attach_single_article_metadata(item, timeout_seconds: int, retries: int, user_agent: str) -> ArticleMetadata:
    metadata_by_url = attach_article_metadata(
        [item],
        timeout_seconds=timeout_seconds,
        retries=retries,
        user_agent=user_agent,
    )
    return metadata_by_url.get(item.url, ArticleMetadata())


def resolve_item_url_without_scrape(item, timeout_seconds: int, retries: int, user_agent: str) -> ArticleMetadata:
    if is_google_news_url(item.url):
        resolved_url = resolve_google_news_url(
            item.url,
            timeout_seconds=timeout_seconds,
            retries=retries,
            user_agent=user_agent,
        )
        if resolved_url != item.url:
            item.url = resolved_url
    if item.image_url and is_google_news_placeholder_image(item.image_url):
        item.image_url = ""
    return ArticleMetadata()


def is_overseas_item(item) -> bool:
    return item.language.lower().startswith("en")


def select_balanced_items(
    items,
    max_items: int,
    overseas_min_items: int = OVERSEAS_MIN_ITEMS,
    domestic_min_items: int = DOMESTIC_MIN_ITEMS,
    max_overseas_items: int | None = None,
) -> list:
    overseas_items = [item for item in items if is_overseas_item(item)]
    domestic_items = [item for item in items if not is_overseas_item(item)]
    selected: list = []
    seen_urls: set[str] = set()

    def add_from(candidates, limit: int) -> None:
        added = 0
        for candidate in candidates:
            if len(selected) >= max_items or added >= limit:
                break
            if (
                max_overseas_items is not None
                and is_overseas_item(candidate)
                and sum(is_overseas_item(item) for item in selected) >= max_overseas_items
            ):
                continue
            if candidate.url in seen_urls:
                continue
            selected.append(candidate)
            seen_urls.add(candidate.url)
            added += 1

    add_from(overseas_items, min(overseas_min_items, max_items))
    add_from(domestic_items, min(domestic_min_items, max_items - len(selected)))
    for candidate in items:
        if len(selected) >= max_items:
            break
        if (
            max_overseas_items is not None
            and is_overseas_item(candidate)
            and sum(is_overseas_item(item) for item in selected) >= max_overseas_items
        ):
            continue
        if candidate.url in seen_urls:
            continue
        selected.append(candidate)
        seen_urls.add(candidate.url)
    return selected


def build_report_notification_text(report_url: str, selected_count: int) -> str:
    return f"昨日 AI 科技新闻已更新，共 {selected_count} 条，请查阅：\n{report_url}"


def write_report_meta(
    meta_path: str | Path,
    *,
    target_date: str,
    report_url: str,
    selected_count: int,
    total_count: int,
    items,
) -> Path:
    path = Path(meta_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "target_date": target_date,
        "report_url": report_url,
        "selected_count": selected_count,
        "total_count": total_count,
        "items": [
            {
                "url": item.url,
                "title": item.title,
                "source": item.source,
                "published_at": item.published_at,
            }
            for item in items
            if item.url
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def notify_from_meta(meta_path: str | Path, db_path: str | Path, webhook_url: str | None, send: bool) -> dict:
    data = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    payload = build_feishu_text_payload(
        build_report_notification_text(
            report_url=data["report_url"],
            selected_count=int(data.get("selected_count", 0)),
        )
    )
    print(payload_to_json(payload))
    if not send:
        logger.info("Send status: skipped (dry run)")
        return payload
    if not webhook_url:
        raise RuntimeError("FEISHU_WEBHOOK_URL is not set")
    response_body = send_feishu_webhook(webhook_url, payload)
    logger.info("Feishu webhook response: %s", response_body or "<empty>")
    for item in data.get("items", []):
        mark_sent_url(
            db_path,
            url=item.get("url", ""),
            title=item.get("title", ""),
            source=item.get("source", ""),
            published_at=item.get("published_at", ""),
        )
    logger.info("Marked sent URLs: %d", len(data.get("items", [])))
    logger.info("Send status: success")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch AI news and prepare Feishu webhook JSON.")
    parser.add_argument("--sources", default="sources.yaml", help="Path to sources.yaml")
    parser.add_argument("--db", default="data/sent_urls.sqlite3", help="SQLite path for sent URLs")
    parser.add_argument("--send", action="store_true", help="Send payload to Feishu webhook")
    parser.add_argument("--date", default=None, help="Target date in YYYY-MM-DD, defaults to yesterday")
    parser.add_argument("--test-feishu", action="store_true", help="Send a minimal Feishu text payload for webhook testing")
    parser.add_argument("--write-meta", default=None, help="Write report notification metadata JSON")
    parser.add_argument("--notify-meta", default=None, help="Send Feishu link notification from metadata JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = load_app_config(sources_path=args.sources, db_path=args.db)
    if args.notify_meta:
        notify_from_meta(args.notify_meta, app.db_path, app.feishu_webhook_url, args.send)
        return 0

    if args.test_feishu:
        payload = build_feishu_text_payload(f"{app.feishu_keyword}｜Feishu webhook test: bot is reachable.")
        print(payload_to_json(payload))
        if args.send:
            if not app.feishu_webhook_url:
                raise RuntimeError("FEISHU_WEBHOOK_URL is not set")
            response_body = send_feishu_webhook(app.feishu_webhook_url, payload)
            logger.info("Feishu webhook response: %s", response_body or "<empty>")
            logger.info("Send status: success")
        else:
            logger.info("Send status: skipped (dry run)")
        return 0

    sources = load_sources(args.sources)
    target_date = args.date or yesterday_in_tz(app.timezone)

    fetch_result = fetch_all_news(
        sources,
        app.timezone,
        timeout_seconds=app.fetch_timeout_seconds,
        retries=app.fetch_retries,
        user_agent=app.user_agent,
    )
    dated_items = filter_items_by_date(fetch_result.items, target_date)
    ranked_items = dedupe_by_title_similarity(dated_items, threshold=0.85)
    raw_unsent_items = filter_unsent(app.db_path, ranked_items)
    quality_raw_items = [item for item in raw_unsent_items if is_raw_item_quality_ok(item)]
    has_volcengine_translator = bool(app.volcengine_access_key_id and app.volcengine_secret_access_key)
    has_azure_translator = bool(app.azure_translator_key and app.azure_translator_region)
    has_stable_translator = has_volcengine_translator or has_azure_translator
    candidate_multiplier = QUALITY_CANDIDATE_MULTIPLIER if has_stable_translator else 3
    overseas_min_items = OVERSEAS_MIN_ITEMS if has_stable_translator else 2
    domestic_min_items = DOMESTIC_MIN_ITEMS if has_stable_translator else 8
    max_overseas_items = None if has_stable_translator else 3
    candidate_items = select_balanced_items(
        quality_raw_items,
        app.max_news_items * candidate_multiplier,
        overseas_min_items=overseas_min_items,
        domestic_min_items=domestic_min_items,
        max_overseas_items=max_overseas_items,
    )
    logger.info("Fetched %d items from %d sources", len(fetch_result.items), len(sources))
    logger.info("After date filter (%s): %d items", target_date, len(dated_items))
    logger.info("After title dedupe: %d items", len(ranked_items))
    logger.info("After URL dedupe: %d items", len(raw_unsent_items))
    logger.info("After raw quality filter: %d items", len(quality_raw_items))
    logger.info("Selected candidates: %d items", len(candidate_items))
    logger.info("Max news items: %d", app.max_news_items)
    logger.info(
        "Translation mode: %s",
        "volcengine" if has_volcengine_translator else "azure" if has_azure_translator else "limited-no-translator",
    )
    if fetch_result.failed_sources:
        logger.warning("Failed sources: %s", ", ".join(fetch_result.failed_sources))
    else:
        logger.info("Failed sources: none")
    for source_name, count in fetch_result.per_source_counts.items():
        logger.info("Source %s fetched %d items", source_name, count)

    enriched = []
    unsent_items = []
    for item in candidate_items:
        if has_stable_translator:
            metadata = attach_single_article_metadata(
                item,
                timeout_seconds=min(app.fetch_timeout_seconds, 5),
                retries=1,
                user_agent=app.user_agent,
            )
        else:
            metadata = resolve_item_url_without_scrape(
                item,
                timeout_seconds=2,
                retries=1,
                user_agent=app.user_agent,
            )
        if is_google_news_url(item.url):
            logger.info("Skipped unresolved Google News item: %s", item.url)
            continue
        enriched_item = enrich_item(
            item,
            app.openai_api_key,
            app.openai_base_url,
            app.openai_model,
            metadata=metadata,
            azure_translator_key=app.azure_translator_key,
            azure_translator_region=app.azure_translator_region,
            volcengine_access_key_id=app.volcengine_access_key_id,
            volcengine_secret_access_key=app.volcengine_secret_access_key,
            volcengine_region=app.volcengine_region,
            openai_summary_enabled=False,
        )
        if not is_content_quality_ok(
            enriched_item.get("title", ""),
            enriched_item.get("summary", ""),
            enriched_item.get("original_title", ""),
            min_summary_chars=80 if has_stable_translator else 60,
        ):
            logger.info("Skipped low-quality item after translation review: %s", item.url)
            continue
        enriched.append(enriched_item)
        unsent_items.append(item)
        if len(enriched) >= app.max_news_items:
            break
    logger.info("Selected after quality review: %d items", len(enriched))

    if app.openai_summary_enabled:
        enhance_final_summaries_with_model(
            enriched,
            openai_api_key=app.openai_api_key,
            openai_base_url=app.openai_base_url,
            openai_summary_model=app.openai_summary_model,
        )
    else:
        logger.info("Model summary enhancement skipped: OPENAI_SUMMARY_ENABLED is false")

    for item, original_item in zip(enriched, unsent_items):
        item["tag"] = "海外" if is_overseas_item(original_item) else "国内"
        item["conclusion"] = item.get("summary", item["title"])[:80]
        if item.get("image_url"):
            item["cover"] = item["image_url"]

    localized_images = localize_report_images(
        enriched,
        output_dir=app.report_output_dir,
        target_date=target_date,
        timeout_seconds=app.fetch_timeout_seconds,
        retries=app.fetch_retries,
        user_agent=app.user_agent,
        max_images_per_item=1,
    )
    cleanup_old_image_dirs(app.report_output_dir, target_date=target_date, keep_days=app.report_keep_days)
    logger.info("Localized report images: %d", localized_images)

    generated_at = datetime.now(ZoneInfo(app.timezone)).strftime("%Y-%m-%d %H:%M %Z")
    report_path = write_report(
        enriched,
        output_dir=app.report_output_dir,
        target_date=target_date,
        total_count=len(fetch_result.items),
        selected_count=len(enriched),
        generated_at=generated_at,
        keep_days=app.report_keep_days,
    )
    report_url = f"{app.report_base_url}/{target_date}.html"
    logger.info("Report path: %s", report_path)
    logger.info("Report url: %s", report_url)

    if args.write_meta:
        meta_path = write_report_meta(
            args.write_meta,
            target_date=target_date,
            report_url=report_url,
            selected_count=len(enriched),
            total_count=len(fetch_result.items),
            items=unsent_items,
        )
        logger.info("Report metadata path: %s", meta_path)

    payload = build_feishu_text_payload(build_report_notification_text(report_url, len(enriched)))
    print(payload_to_json(payload))

    if args.send:
        if not app.feishu_webhook_url:
            raise RuntimeError("FEISHU_WEBHOOK_URL is not set")
        response_body = send_feishu_webhook(app.feishu_webhook_url, payload)
        logger.info("Feishu webhook response: %s", response_body or "<empty>")
        for item in unsent_items:
            mark_sent(app.db_path, item)
        logger.info("Send status: success")
    else:
        logger.info("Send status: skipped (dry run)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
