from __future__ import annotations

import json
from urllib import request, error


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


def _call_openai_chat(
    api_key: str,
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
) -> str:
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    chat_url = base_url.rstrip("/") + "/chat/completions"
    req = request.Request(
        chat_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        raise RuntimeError(f"OpenAI request failed: {exc.read().decode('utf-8', errors='ignore')}") from exc

    return body["choices"][0]["message"]["content"].strip()


def translate_to_zh(text: str, api_key: str | None, model: str = "gpt-4.1-mini") -> str:
    return translate_to_zh_with_base_url(text, api_key=api_key, base_url="https://api.openai.com/v1", model=model)


def translate_to_zh_with_base_url(
    text: str,
    api_key: str | None,
    base_url: str,
    model: str = "gpt-4.1-mini",
) -> str:
    if not text.strip():
        return ""
    if not api_key:
        return text
    return _call_openai_chat(
        api_key=api_key,
        base_url=base_url,
        model=model,
        system_prompt="You are a professional translation assistant. Translate the user text into concise, natural Chinese. Keep product names and proper nouns accurate.",
        user_prompt=text,
    )
