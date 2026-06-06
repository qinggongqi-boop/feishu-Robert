from __future__ import annotations

from summarize import clean_model_summary, summarize_to_zh


def test_summarize_to_zh_retries_once_on_503(monkeypatch):
    calls = []

    def fake_call_openai_chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError("OpenAI request failed with HTTP 503")
        return "OpenAI 发布新的推理模型，面向开发者开放 API，并提升代码、数学和规划任务的稳定性。"

    monkeypatch.setattr("summarize._call_openai_chat", fake_call_openai_chat)
    monkeypatch.setattr("summarize.time.sleep", lambda seconds: None)

    summary = summarize_to_zh(
        "OpenAI 发布新模型",
        "OpenAI says the release is designed for production use cases.",
        api_key="test-key",
        base_url="https://api.example.com/v1",
        model="gpt-4.1-mini",
        retries=1,
    )

    assert len(calls) == 2
    assert "OpenAI 发布新的推理模型" in summary


def test_summarize_to_zh_does_not_retry_non_503(monkeypatch):
    calls = []

    def fake_call_openai_chat(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("OpenAI request failed with HTTP 401")

    monkeypatch.setattr("summarize._call_openai_chat", fake_call_openai_chat)
    monkeypatch.setattr("summarize.time.sleep", lambda seconds: None)

    try:
        summarize_to_zh(
            "OpenAI 发布新模型",
            "OpenAI says the release is designed for production use cases.",
            api_key="test-key",
            retries=1,
        )
    except RuntimeError as exc:
        assert "HTTP 401" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError")

    assert len(calls) == 1


def test_clean_model_summary_removes_labels():
    assert clean_model_summary("摘要：发生了什么：OpenAI 发布新模型") == "OpenAI 发布新模型。"
