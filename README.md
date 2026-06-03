# Python AI News to Feishu

这是一个用于每天抓取国内外 AI 新闻，并输出或发送到飞书的 Python 项目骨架。

## 功能

- 支持 RSS 和 Google News RSS
- 通过 `sources.yaml` 配置新闻源
- 筛选昨天发布的新闻
- 支持国内中文新闻和国外英文新闻
- 英文新闻可调用 OpenAI API 翻译为中文
- 支持生成中文摘要
- 使用 SQLite 存储已发送 URL，避免重复推送
- 输出飞书 webhook 消息 JSON

## 文件说明

- `main.py`：主入口，抓取、筛选、翻译、摘要、构造飞书消息
- `fetch_news.py`：RSS 和 Google News RSS 抓取
- `translate.py`：OpenAI 翻译
- `summarize.py`：OpenAI 中文摘要
- `feishu.py`：飞书 webhook JSON 构建和发送
- `dedupe.py`：SQLite 去重
- `config.py`：配置加载
- `sources.yaml`：新闻源示例

## 安装依赖

建议使用 Python 3.10+。

```bash
pip install -r requirements.txt
```

## 环境变量

需要在 GitHub Secrets 或本地环境中配置：

- `FEISHU_WEBHOOK_URL`
- `OPENAI_API_KEY`

可选配置：

- `OPENAI_MODEL`，默认 `gpt-4.1-mini`
- `FEISHU_MESSAGE_FORMAT`，默认 `card`
- `APP_TIMEZONE`，默认 `Asia/Shanghai`

## 运行方式

先只输出飞书 JSON，不发送：

```bash
python main.py
```

发送到飞书并写入 SQLite 去重库：

```bash
python main.py --send
```

指定某一天：

```bash
python main.py --date 2026-06-02
```

## GitHub Secrets 配置

在 GitHub 仓库的 `Settings -> Secrets and variables -> Actions` 中添加：

1. `FEISHU_WEBHOOK_URL`
   - 飞书机器人的 webhook 地址
2. `OPENAI_API_KEY`
   - OpenAI API Key，用于英文翻译和中文摘要

如果你在 GitHub Actions 中定时运行，可以在 workflow 中读取这两个 secrets，并执行：

```yaml
env:
  FEISHU_WEBHOOK_URL: ${{ secrets.FEISHU_WEBHOOK_URL }}
  OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

## 备注

- SQLite 默认路径为 `data/sent_urls.sqlite3`
- `sources.yaml` 里的 `kind` 支持 `rss` 和 `google_news`
- `language` 建议写 `zh` 或 `en`，便于决定是否翻译
- 飞书 webhook 的真正图片组件需要 `image_key`，因此当前实现会优先生成卡片，并在只有图片 URL 时显示封面链接；如果后续接入飞书图片上传接口，可直接在卡片中展示真实图片
