# Daily AI Tech News

每天自动抓取前一天国内外 AI / 科技圈重要新闻，生成公开网页报告，并通过飞书机器人发送一个可点击链接。

## 当前效果

- GitHub Actions 每天北京时间 09:13 自动运行。
- 抓取 RSS / Google News RSS 新闻源。
- 只筛选北京时间昨天发布的新闻。
- AI 新闻优先，科技圈重大新闻作为补充。
- 英文新闻标题和概述会翻译成中文。
- 每天精选最多 15 条。
- SQLite 记录已推送 URL，避免连续几天重复推同一篇。
- 生成 GitHub Pages 静态页面，首页永远跳转到最新一期。
- 飞书只发送一句提醒和报告链接：

```text
昨日 AI 科技新闻已更新，共 15 条，请查阅：
https://qinggongqi-boop.github.io/feishu-Robert/YYYY-MM-DD.html
```

## 网页报告内容

每条新闻包含：

- 中文主标题
- 原文标题
- 原文配图，优先 1 张，最多支持 2 张
- 200-300 字左右中文概述
- 新闻来源
- 原文链接

如果没有抓到图片，页面会自动显示简洁占位背景。

## 文件说明

- `main.py`：主入口，负责抓取、筛选、翻译、摘要、生成报告、发送飞书通知
- `fetch_news.py`：RSS / Google News RSS 抓取、日期过滤、标题相似去重、图片抓取
- `translate.py`：OpenAI 兼容接口翻译
- `summarize.py`：中文概述生成
- `report.py`：GitHub Pages HTML 报告生成
- `feishu.py`：飞书 webhook payload 构建和发送
- `dedupe.py`：SQLite URL 去重
- `config.py`：环境变量和配置加载
- `sources.yaml`：新闻源配置
- `.github/workflows/daily_news.yml`：每日自动运行和 Pages 部署

## 本地运行

安装依赖：

```bash
pip install -r requirements.txt
```

只生成报告，不发送飞书：

```bash
python main.py
```

生成报告并写出通知元数据：

```bash
python main.py --write-meta logs/report_meta.json
```

根据元数据发送飞书链接，并把 URL 写入去重库：

```bash
python main.py --notify-meta logs/report_meta.json --send
```

指定日期：

```bash
python main.py --date 2026-06-05
```

测试飞书 webhook：

```bash
python main.py --test-feishu --send
```

## GitHub Secrets

在仓库 `Settings -> Secrets and variables -> Actions` 中配置：

- `FEISHU_WEBHOOK_URL`：飞书机器人 webhook
- `OPENAI_API_KEY`：OpenAI 或兼容服务 API Key
- `OPENAI_BASE_URL`：OpenAI 兼容接口地址，例如 `https://codexx.dns.army/v1`
- `OPENAI_MODEL`：模型名，例如 `gpt5.4-mini`

可选：

- `FEISHU_KEYWORD`：如果飞书机器人开启了关键词校验，可以设置关键词

不要把任何 key 写入代码或提交到公开仓库。

## GitHub Pages

仓库需要启用 GitHub Pages，并选择：

- Source: `GitHub Actions`

workflow 会自动：

1. 抓取和筛选新闻。
2. 生成 `docs/YYYY-MM-DD.html` 和 `docs/index.html`。
3. 部署 GitHub Pages。
4. Pages 部署成功后，再发送飞书链接。
5. 飞书发送成功后，记录已发送 URL。

## 新闻源

新增或调整新闻源只需要修改 `sources.yaml`。

推荐保持：

- 官方博客或权威媒体优先级更高。
- Google News RSS 用于补充热门新闻。
- 国内中文源和国外英文源都保留。

## 测试

```bash
pytest -q
```

当前测试覆盖：

- 昨天新闻日期判断
- 英文新闻翻译字段完整性
- URL 去重
- 飞书 webhook JSON
- 报告页 HTML
- 部署后通知元数据和已发送 URL 标记
