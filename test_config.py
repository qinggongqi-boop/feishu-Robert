from __future__ import annotations

from config import load_app_config


def test_app_config_defaults_to_post_and_15_items(monkeypatch):
    monkeypatch.delenv("FEISHU_MESSAGE_FORMAT", raising=False)
    monkeypatch.delenv("MAX_NEWS_ITEMS", raising=False)
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    monkeypatch.delenv("MAX_IMAGE_UPLOADS", raising=False)

    app = load_app_config()

    assert app.feishu_message_format == "post"
    assert app.max_news_items == 15
    assert app.feishu_app_id is None
    assert app.feishu_app_secret is None
    assert app.max_image_uploads == 5
    assert app.report_base_url == "https://qinggongqi-boop.github.io/feishu-Robert"
    assert app.report_output_dir.name == "docs"


def test_app_config_reads_volcengine_translator_env(monkeypatch):
    monkeypatch.setenv("VOLCENGINE_ACCESS_KEY_ID", "test-ak")
    monkeypatch.setenv("VOLCENGINE_SECRET_ACCESS_KEY", "test-sk")
    monkeypatch.setenv("VOLCENGINE_REGION", "cn-north-1")

    app = load_app_config()

    assert app.volcengine_access_key_id == "test-ak"
    assert app.volcengine_secret_access_key == "test-sk"
    assert app.volcengine_region == "cn-north-1"
