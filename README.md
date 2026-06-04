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
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `FEISHU_APP_ID`，可选，用于上传新闻图片到飞书并在卡片中显示真图
- `FEISHU_APP_SECRET`，可选，用于上传新闻图片到飞书并在卡片中显示真图

可选配置：

- `OPENAI_MODEL`，默认 `gpt-4.1-mini`
- `OPENAI_BASE_URL`，默认 `https://api.openai.com/v1`
- `FEISHU_MESSAGE_FORMAT`，默认 `post`
- `FEISHU_KEYWORD`，默认 `AI news 今日`，仅在飞书机器人开启关键词校验时需要
- `MAX_IMAGE_UPLOADS`，默认 `5`，控制每天最多上传几张封面图到飞书
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
  OPENAI_BASE_URL: ${{ secrets.OPENAI_BASE_URL }}
  OPENAI_MODEL: ${{ secrets.OPENAI_MODEL }}
  FEISHU_APP_ID: ${{ secrets.FEISHU_APP_ID }}
  FEISHU_APP_SECRET: ${{ secrets.FEISHU_APP_SECRET }}
```

## 飞书机器人安全设置

如果你希望富文本 `post` 或卡片消息稳定送达，建议在飞书机器人详情中关闭“自定义关键词”校验。

操作方式：

1. 打开目标群聊右侧的机器人设置。
2. 点击对应机器人详情。
3. 在“安全设置”里取消勾选“自定义关键词”。
4. 点击右下角“保存”。

如果保留关键词校验，请确保消息正文或标题包含 `FEISHU_KEYWORD`。当前默认关键词是 `AI news 今日`。

## 显示真正图片

飞书 webhook 不能直接把新闻网站外链图片显示成图片组件。要显示真正图片，需要先调用飞书开放平台图片上传接口，把外链图片上传到飞书，拿到 `image_key` 后再构造卡片。

配置步骤：

1. 进入飞书开放平台，创建或打开一个企业自建应用。
2. 在“凭证与基础信息”页面复制 `App ID` 和 `App Secret`。
3. 在应用权限里添加图片上传相关权限，通常需要 `im:resource`。
4. 发布或启用该应用，使权限生效。
5. 在 GitHub 仓库 `Settings -> Secrets and variables -> Actions` 中新增：
   `FEISHU_APP_ID`
   `FEISHU_APP_SECRET`
6. 保持 workflow 运行即可。代码会自动下载新闻封面图，上传到飞书并在卡片中展示。

## 备注

- SQLite 默认路径为 `data/sent_urls.sqlite3`
- `sources.yaml` 里的 `kind` 支持 `rss` 和 `google_news`
- `language` 建议写 `zh` 或 `en`，便于决定是否翻译
- 未配置 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 时，消息会显示可点击的配图链接

## 一句话说明

推送每日的 AI 新闻。
