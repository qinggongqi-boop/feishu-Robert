# Daily AI Tech News

每天自动抓取前一天国内外 AI / 科技圈重要新闻，生成公开网页报告，并通过飞书机器人发送一个可点击链接。

项目现在包含两条自动化链路：

- `main.py`：原有 AI 科技新闻网页报告，生成 GitHub Pages 页面后给飞书发送链接。
- `daily_brief.py`：每日增长情报简报，直接生成中文飞书富文本，面向美国服装独立站、Meta 广告、AI 视频、Agent 自动化和跨境电商增长机会。

## 当前效果

- GitHub Actions 工作日北京时间 09:05 自动运行，周末北京时间 11:01 自动运行，并额外重试触发。
- 发送窗口保护已关闭：无论 GitHub schedule 是否延迟，只要 workflow 被触发就会继续生成报告并发送飞书通知。
- 同一日期报告只会发送一次，避免多次触发造成重复推送。
- 如果希望更准点，可以用外部定时器调用 `workflow_dispatch`；触发后不再检查北京时间发送窗口。
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
- `translate.py`：火山引擎机器翻译优先，Azure 可选备用，Google 免费接口兜底
- `summarize.py`：中文概述生成
- `report.py`：GitHub Pages HTML 报告生成
- `feishu.py`：飞书 webhook payload 构建和发送
- `dedupe.py`：SQLite URL 去重
- `config.py`：环境变量和配置加载
- `sources.yaml`：新闻源配置
- `daily_brief.py`：每日增长情报简报入口，直接推送飞书富文本或纯文本
- `feeds.json`：增长情报简报资讯源配置
- `.env.example`：增长情报简报本地环境变量示例
- `launchd.com.user.feishu.dailybrief.plist.example`：Mac 本地定时任务模板
- `.github/workflows/daily_news.yml`：每日自动运行和 Pages 部署
- `.github/workflows/feishu_daily_brief.yml`：每日增长情报飞书简报 workflow

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

报告默认保留最近 7 天，可通过 `REPORT_KEEP_DAYS` 调整。
精选新闻图片会优先下载到 `docs/assets/images/YYYY-MM-DD/`，报告页引用 GitHub Pages 本地图片；下载失败时自动显示占位图，避免外链破图。

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

## 每日增长情报简报

`daily_brief.py` 会抓取 `feeds.json` 中的 RSS 源，筛选最近 `LOOKBACK_HOURS` 小时内容，按 topic 限量后调用 OpenAI 兼容接口生成中文增长情报简报，并推送飞书自定义机器人。

默认关注三个板块：

- `AI / 模型 / Codex / Agent`
- `跨境电商 / Meta广告 / 爆款素材`
- `全球商业 / 科技公司动态`

本地配置：

```bash
cp .env.example .env
```

然后在 `.env` 中填写：

```env
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4.1-mini

FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
FEISHU_SECRET=

LOOKBACK_HOURS=30
MAX_ARTICLES_PER_TOPIC=10
FEEDS_JSON=feeds.json
```

如果飞书机器人开启了签名校验，填写 `FEISHU_SECRET`；未开启可以留空。不要把 `.env` 提交到 GitHub。

发送测试消息，不抓取 RSS，不调用 LLM：

```bash
python3 daily_brief.py --test
```

正式运行，默认发送飞书富文本 `post`：

```bash
python3 daily_brief.py
```

只发送纯文本消息：

```bash
python3 daily_brief.py --text-only
```

覆盖抓取窗口和每个板块保留数量：

```bash
python3 daily_brief.py --lookback-hours 48 --max-per-topic 15
```

使用自定义资讯源：

```bash
python3 daily_brief.py --feeds feeds.json
```

运行日志会写入：

```text
logs/dailybrief.out.log
logs/dailybrief.err.log
```

如果单个 RSS 源失败，程序会记录 warning 并继续抓取其他源。如果 LLM 调用失败，程序会停止推送，避免把错误内容发到飞书。如果富文本发送失败，会自动尝试纯文本兜底。

## GitHub Secrets

在仓库 `Settings -> Secrets and variables -> Actions` 中配置：

- `FEISHU_WEBHOOK_URL`：飞书机器人 webhook
- `OPENAI_API_KEY`：OpenAI 或兼容服务 API Key
- `OPENAI_BASE_URL`：OpenAI 兼容接口地址，例如 `https://codexx.dns.army/v1`
- `OPENAI_MODEL`：模型名，例如 `gpt5.4-mini`
- `FEISHU_WEBHOOK`：增长情报简报使用的飞书机器人 webhook。也可以继续使用旧变量 `FEISHU_WEBHOOK_URL`
- `FEISHU_SECRET`：飞书机器人签名密钥。未开启签名校验时留空
- `OPENAI_SUMMARY_API_KEY`：摘要专用 API Key。可选；不填时沿用 `OPENAI_API_KEY`
- `OPENAI_SUMMARY_BASE_URL`：摘要专用兼容接口地址。可选；阿里云百炼中国大陆可填 `https://dashscope.aliyuncs.com/compatible-mode/v1`
- `OPENAI_SUMMARY_MODEL`：摘要专用模型。可选；不填时默认跟随 `OPENAI_MODEL`。如果当前模型不稳定，可以单独填写服务商支持的更稳定模型
- `VOLCENGINE_ACCESS_KEY_ID`：火山引擎 Access Key ID
- `VOLCENGINE_SECRET_ACCESS_KEY`：火山引擎 Secret Access Key
- `VOLCENGINE_REGION`：火山引擎区域，默认可填 `cn-north-1`

可选：

- `FEISHU_KEYWORD`：如果飞书机器人开启了关键词校验，可以设置关键词
- `AZURE_TRANSLATOR_KEY`：Azure AI Translator 的 Key，作为火山引擎不可用时的备用
- `AZURE_TRANSLATOR_REGION`：Azure AI Translator 资源所在区域，例如 `eastasia`、`southeastasia`
- `OPENAI_SUMMARY_ENABLED`：是否启用 OpenAI 兼容接口做理解式摘要。GitHub Actions 默认设为 `true`

阿里云百炼的 `qwen-turbo` 不需要自行部署模型；创建 API Key 后，把 `OPENAI_SUMMARY_BASE_URL` 设为百炼兼容地址，并把 `OPENAI_SUMMARY_MODEL` 设为 `qwen-turbo` 即可调用。

不要把任何 key 写入代码或提交到公开仓库。

## 外部定时器

GitHub Actions 的 `schedule` 可能延迟。发送窗口保护已经关闭，所以延迟触发也会正常生成报告并发送飞书通知。如果你希望更准点，可以在 cron-job.org、UptimeRobot 或 Cloudflare Workers Cron 中配置两个 HTTP POST：

- 工作日北京时间 09:05
- 周末北京时间 11:01

请求地址：

```text
https://api.github.com/repos/qinggongqi-boop/feishu-Robert/actions/workflows/daily_news.yml/dispatches
```

请求方法：`POST`

请求头：

```text
Accept: application/vnd.github+json
Authorization: Bearer YOUR_GITHUB_TOKEN
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

请求体：

```json
{"ref":"main"}
```

GitHub Token 建议使用 fine-grained token，只授予仓库 `qinggongqi-boop/feishu-Robert` 的 `Actions: Read and write` 权限。不要把 token 写进代码或公开页面。

## GitHub Actions 增长情报简报

`.github/workflows/feishu_daily_brief.yml` 默认每天 `01:00 UTC` 自动运行，对应：

- 北京时间：09:00
- 日本时间：10:00

也支持在 GitHub Actions 页面手动 `workflow_dispatch`。

需要在仓库 `Settings -> Secrets and variables -> Actions` 中配置：

- `OPENAI_API_KEY`，也兼容旧的 `OPENAI_SUMMARY_API_KEY`
- `OPENAI_BASE_URL`，可选；不填时默认 `https://api.openai.com/v1`，也兼容旧的 `OPENAI_SUMMARY_BASE_URL`
- `OPENAI_MODEL`，也兼容旧的 `OPENAI_SUMMARY_MODEL`
- `FEISHU_WEBHOOK`，也兼容旧的 `FEISHU_WEBHOOK_URL`
- `FEISHU_SECRET`，可选；飞书机器人未开启签名时不填

手动测试时可以选择 `test=true`，workflow 会执行：

```bash
python daily_brief.py --test
```

正式运行时执行：

```bash
python daily_brief.py
```

## Mac launchd 定时

本地 Mac 定时任务模板在：

```text
launchd.com.user.feishu.dailybrief.plist.example
```

使用步骤：

1. 复制模板到 `~/Library/LaunchAgents/com.user.feishu.dailybrief.plist`
2. 把模板里的 `/ABSOLUTE/PATH/TO/PROJECT` 替换为项目绝对路径
3. 确认 `ProgramArguments` 使用的是项目虚拟环境里的 Python，例如 `.venv/bin/python`
4. 加载任务：

```bash
launchctl unload ~/Library/LaunchAgents/com.user.feishu.dailybrief.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/com.user.feishu.dailybrief.plist
launchctl start com.user.feishu.dailybrief
```

默认每天上午 9:00 执行，日志写入 `logs/dailybrief.out.log` 和 `logs/dailybrief.err.log`。

## 火山引擎机器翻译

当前推荐使用火山引擎机器翻译做英文标题和正文翻译，适合国内账号和人民币结算场景。

配置步骤：

1. 在火山引擎控制台开通机器翻译。
2. 在访问控制或密钥管理中创建 Access Key。
3. 在 GitHub 仓库 `Settings -> Secrets and variables -> Actions` 中新增：
   - `VOLCENGINE_ACCESS_KEY_ID`
   - `VOLCENGINE_SECRET_ACCESS_KEY`
   - `VOLCENGINE_REGION`，通常填 `cn-north-1`

运行时策略：

1. 有火山引擎 Secrets 时，优先使用火山引擎机器翻译。
2. 火山引擎未配置或请求失败时，如果配置了 Azure，则使用 Azure Translator。
3. 候选筛选阶段只生成本地摘要，先选出最终 15 条，避免大量调用模型接口。
4. 最终 15 条确定后，如果有 `OPENAI_API_KEY`，再使用 OpenAI 兼容模型做理解式中文摘要，重点讲清楚“发生了什么、为什么重要、后续看什么”。
5. 模型遇到 `503` 会自动重试 1 次；模型摘要不合格或接口失败时，会自动回退到本地摘要。
6. 报告页每条新闻会显示摘要来源：`模型摘要` 或 `本地回退`，方便排查质量问题。
7. 两者都未配置时，进入轻量模式：优先中文新闻，少量保留海外新闻，避免英文长文被免费接口乱翻译。
8. 如果标题或摘要翻译后仍明显是英文、乱码、菜单广告或内容过短，会跳过该条新闻。

## Azure Translator 备用

如果你有 Azure 资源，也可以作为备用翻译服务。

配置步骤：

1. 进入 Azure Portal，创建 `Translator` 或 `Azure AI services` 翻译资源。
2. 定价层选择免费层 `F0`，如果账号和区域支持的话。
3. 在资源页面的 `Keys and Endpoint` 中复制一个 Key。
4. 记录资源的 Region，例如 `eastasia` 或 `southeastasia`。
5. 在 GitHub 仓库 `Settings -> Secrets and variables -> Actions` 中新增 `AZURE_TRANSLATOR_KEY` 和 `AZURE_TRANSLATOR_REGION`。

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
- 每日增长情报 feeds 读取
- lookback 时间筛选
- 每 topic 限量
- 飞书签名
- 飞书富文本结构
- 富文本失败后的纯文本兜底
- 飞书 webhook JSON
- 报告页 HTML
- 部署后通知元数据和已发送 URL 标记
