from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from pathlib import Path


def _clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def _truncate_summary(summary: str, min_chars: int = 100, max_chars: int = 500) -> str:
    text = _clean_text(summary)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit("，", 1)[0].rsplit("。", 1)[0]
    if len(cut) < min_chars:
        cut = text[:max_chars]
    return cut.rstrip("，。；;,. ") + "。"


def _item_images(item: dict) -> list[str]:
    images = item.get("image_urls") or []
    if isinstance(images, str):
        images = [images]
    images.extend([item.get("cover", ""), item.get("image_url", "")])
    clean_images: list[str] = []
    for image_url in images:
        if image_url and image_url not in clean_images:
            clean_images.append(str(image_url))
    return clean_images[:2]


def _image_html(item: dict) -> str:
    image_urls = _item_images(item)
    title = escape(item.get("title") or item.get("original_title") or "新闻配图")
    if not image_urls:
        return """
        <div class="image placeholder">
          <div class="orb"></div>
          <span>AI NEWS</span>
        </div>
        """
    images_html = "\n".join(
        f'<img src="{escape(image_url)}" alt="{title}" loading="lazy" referrerpolicy="no-referrer" />'
        for image_url in image_urls
    )
    image_count_class = "two-images" if len(image_urls) == 2 else "one-image"
    return f"""
    <figure class="image {image_count_class}">
      {images_html}
    </figure>
    """


def _article_html(item: dict[str, str], index: int) -> str:
    title = escape(item.get("title", "未命名新闻"))
    original_title = escape(item.get("original_title") or item.get("raw_title") or item.get("title", ""))
    source = escape(item.get("source", "未知来源"))
    tag = escape(item.get("tag", "新闻"))
    url = escape(item.get("url", ""))
    summary = escape(_truncate_summary(item.get("summary", "")))
    original_title_html = f'<p class="original-title">{original_title}</p>' if original_title and original_title != title else ""
    link_html = (
        f'<a class="source-link" href="{url}" target="_blank" rel="noopener noreferrer">阅读原文</a>'
        if url
        else '<span class="source-link disabled">暂无原文链接</span>'
    )

    return f"""
    <article class="news-card">
      <div class="rank">{index:02d}</div>
      {_image_html(item)}
      <div class="content">
        <div class="meta">
          <span class="tag">{tag}</span>
          <span>{source}</span>
        </div>
        <h2>{title}</h2>
        {original_title_html}
        <p class="summary">{summary}</p>
        <div class="actions">{link_html}</div>
      </div>
    </article>
    """


def build_report_html(
    items: list[dict[str, str]],
    target_date: str,
    total_count: int,
    selected_count: int,
    generated_at: str,
) -> str:
    cards = "\n".join(_article_html(item, index) for index, item in enumerate(items, start=1))
    if not cards:
        cards = '<section class="empty">今天没有筛选到符合条件的新闻。</section>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light" />
  <title>昨日 AI 科技新闻｜{escape(target_date)}</title>
  <style>
    :root {{
      --ink: #14213d;
      --muted: #64748b;
      --line: rgba(15, 23, 42, 0.11);
      --paper: #fffaf1;
      --card: rgba(255, 255, 255, 0.78);
      --accent: #0f766e;
      --accent-2: #f59e0b;
      --shadow: 0 24px 80px rgba(15, 23, 42, 0.12);
    }}
    * {{ box-sizing: border-box; }}
    html {{
      overflow-x: hidden;
    }}
    body {{
      margin: 0;
      overflow-x: hidden;
      color: var(--ink);
      font-family: ui-serif, "Songti SC", "Noto Serif CJK SC", Georgia, serif;
      background:
        radial-gradient(circle at top left, rgba(20, 184, 166, 0.22), transparent 34rem),
        radial-gradient(circle at 85% 12%, rgba(245, 158, 11, 0.22), transparent 28rem),
        linear-gradient(135deg, #fff7ed 0%, #f8fafc 54%, #ecfeff 100%);
      min-height: 100vh;
    }}
    a {{ color: inherit; }}
    img, figure {{
      max-width: 100%;
    }}
    .page {{
      width: min(1120px, calc(100% - 32px));
      max-width: 100%;
      margin: 0 auto;
      padding: 42px 0 60px;
    }}
    .hero {{
      position: relative;
      overflow: hidden;
      padding: clamp(28px, 6vw, 64px);
      border: 1px solid var(--line);
      border-radius: 34px;
      background: rgba(255, 255, 255, 0.64);
      box-shadow: var(--shadow);
      backdrop-filter: blur(18px);
    }}
    .hero::after {{
      content: "";
      position: absolute;
      right: -120px;
      top: -120px;
      width: 300px;
      height: 300px;
      border-radius: 50%;
      background: conic-gradient(from 120deg, #0f766e, #f59e0b, #38bdf8, #0f766e);
      opacity: 0.18;
    }}
    .eyebrow {{
      display: inline-flex;
      gap: 8px;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(15, 118, 110, 0.1);
      color: var(--accent);
      font: 700 13px/1.1 ui-sans-serif, system-ui, sans-serif;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 18px 0 14px;
      font-size: clamp(38px, 8vw, 82px);
      line-height: 0.95;
      letter-spacing: -0.06em;
    }}
    .lede {{
      max-width: 760px;
      color: #334155;
      font-size: clamp(17px, 2.3vw, 22px);
      line-height: 1.75;
    }}
    .stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 28px;
    }}
    .stat {{
      padding: 12px 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.62);
      font: 700 14px/1.2 ui-sans-serif, system-ui, sans-serif;
    }}
    .grid {{
      display: grid;
      gap: 22px;
      margin-top: 28px;
    }}
    .news-card {{
      position: relative;
      display: grid;
      grid-template-columns: minmax(220px, 34%) minmax(0, 1fr);
      gap: 0;
      max-width: 100%;
      min-width: 0;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 30px;
      background: var(--card);
      box-shadow: 0 16px 48px rgba(15, 23, 42, 0.09);
      backdrop-filter: blur(14px);
    }}
    .rank {{
      position: absolute;
      top: 16px;
      left: 16px;
      z-index: 2;
      padding: 8px 10px;
      border-radius: 14px;
      background: rgba(15, 23, 42, 0.78);
      color: white;
      font: 800 13px/1 ui-sans-serif, system-ui, sans-serif;
    }}
    .image {{
      min-height: 260px;
      margin: 0;
      min-width: 0;
      background: #0f172a;
    }}
    .image img {{
      width: 100%;
      height: 100%;
      min-height: 260px;
      display: block;
      object-fit: cover;
    }}
    .two-images {{
      display: grid;
      grid-template-rows: 1fr 1fr;
      gap: 2px;
    }}
    .two-images img {{
      min-height: 129px;
    }}
    .placeholder {{
      display: grid;
      place-items: center;
      position: relative;
      overflow: hidden;
      color: rgba(255,255,255,0.86);
      font: 900 22px/1 ui-sans-serif, system-ui, sans-serif;
      letter-spacing: 0.16em;
    }}
    .placeholder .orb {{
      position: absolute;
      width: 220px;
      height: 220px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(56,189,248,0.9), rgba(15,118,110,0.38), transparent 68%);
      filter: blur(1px);
    }}
    .placeholder span {{ position: relative; }}
    .content {{
      min-width: 0;
      padding: clamp(22px, 4vw, 38px);
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--muted);
      font: 700 13px/1.2 ui-sans-serif, system-ui, sans-serif;
    }}
    .tag {{
      color: var(--accent);
      background: rgba(15, 118, 110, 0.1);
      padding: 4px 9px;
      border-radius: 999px;
    }}
    h2 {{
      margin: 14px 0 8px;
      font-size: clamp(24px, 4.2vw, 42px);
      line-height: 1.12;
      letter-spacing: -0.04em;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .original-title {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
      margin: 0 0 18px;
      font-family: ui-sans-serif, system-ui, sans-serif;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .summary {{
      margin: 0;
      color: #334155;
      font-size: 17px;
      line-height: 1.9;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .actions {{
      margin-top: 22px;
    }}
    .source-link {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      padding: 0 18px;
      border-radius: 999px;
      background: var(--ink);
      color: white;
      text-decoration: none;
      font: 800 14px/1 ui-sans-serif, system-ui, sans-serif;
      max-width: 100%;
      white-space: normal;
      text-align: center;
    }}
    .source-link.disabled {{
      background: #cbd5e1;
      color: #475569;
    }}
    footer {{
      margin-top: 32px;
      color: var(--muted);
      text-align: center;
      font: 14px/1.7 ui-sans-serif, system-ui, sans-serif;
    }}
    .empty {{
      padding: 40px;
      border-radius: 24px;
      background: white;
      text-align: center;
    }}
    @media (max-width: 760px) {{
      .page {{ width: min(100% - 20px, 1120px); padding-top: 18px; }}
      .hero {{ border-radius: 24px; }}
      .news-card {{ grid-template-columns: minmax(0, 1fr); border-radius: 24px; }}
      .image, .image img {{ min-height: 210px; }}
      .content {{ padding: 22px; }}
    }}
    @media (max-width: 420px) {{
      .page {{ width: min(100% - 12px, 1120px); }}
      .hero {{ padding: 22px 18px; }}
      .content {{ padding: 18px; }}
      h1 {{ font-size: clamp(34px, 14vw, 52px); }}
      h2 {{ font-size: clamp(22px, 7vw, 30px); }}
      .summary {{ font-size: 16px; line-height: 1.82; }}
      .image, .image img {{ min-height: 188px; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <span class="eyebrow">Daily Briefing</span>
      <h1>昨日 AI 科技新闻</h1>
      <p class="lede">AI 为主，兼顾科技圈重大动态。每条新闻保留原文入口，并整理为中文概述，方便快速判断是否值得深入阅读。</p>
      <div class="stats">
        <div class="stat">日期：{escape(target_date)}</div>
        <div class="stat">共抓取 {total_count} 条</div>
        <div class="stat">精选 {selected_count} 条</div>
      </div>
    </section>
    <section class="grid">
      {cards}
    </section>
    <footer>
      生成时间：{escape(generated_at)}。内容由公开 RSS / Google News RSS 聚合生成，摘要仅供快速阅读，事实以原文为准。
    </footer>
  </main>
</body>
</html>
"""


def write_report(
    items: list[dict[str, str]],
    output_dir: Path,
    target_date: str,
    total_count: int,
    selected_count: int,
    generated_at: str,
    keep_days: int = 30,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{target_date}.html"
    report_path.write_text(
        build_report_html(
            items=items,
            target_date=target_date,
            total_count=total_count,
            selected_count=selected_count,
            generated_at=generated_at,
        ),
        encoding="utf-8",
    )
    (output_dir / "index.html").write_text(
        '<!doctype html><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0; url={target_date}.html">'
        f'<title>跳转到最新 AI 科技新闻</title>'
        f'<p>正在打开最新一期：<a href="{target_date}.html">{target_date}</a></p>',
        encoding="utf-8",
    )
    _cleanup_old_reports(output_dir, target_date=target_date, keep_days=keep_days)
    return report_path


def _cleanup_old_reports(output_dir: Path, target_date: str, keep_days: int) -> None:
    try:
        cutoff = datetime.fromisoformat(target_date).date() - timedelta(days=keep_days - 1)
    except ValueError:
        return
    for path in output_dir.glob("*.html"):
        if path.name == "index.html":
            continue
        try:
            report_date = datetime.fromisoformat(path.stem).date()
        except ValueError:
            continue
        if report_date < cutoff:
            path.unlink()
