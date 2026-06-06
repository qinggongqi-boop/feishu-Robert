from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from urllib import request, error
from urllib.parse import quote
from uuid import uuid4

import requests


OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
VOLCENGINE_TRANSLATE_HOST = "translate.volcengineapi.com"
VOLCENGINE_TRANSLATE_ACTION = "TranslateText"
VOLCENGINE_TRANSLATE_VERSION = "2020-06-01"
VOLCENGINE_TRANSLATE_SERVICE = "translate"


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
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if temperature is not None:
        payload["temperature"] = temperature
    return _post_openai_chat(api_key=api_key, base_url=base_url, payload=payload)


def _post_openai_chat(api_key: str, base_url: str, payload: dict) -> str:
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
        error_body = exc.read().decode("utf-8", errors="ignore")
        if "temperature" in error_body and "temperature" in payload:
            fallback_payload = dict(payload)
            fallback_payload.pop("temperature", None)
            return _post_openai_chat(api_key=api_key, base_url=base_url, payload=fallback_payload)
        raise RuntimeError(f"OpenAI request failed: {error_body}") from exc

    try:
        return body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"OpenAI response format is unsupported: {body}") from exc


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


def translate_to_zh_fallback(text: str) -> str:
    """Best-effort no-key translation fallback used when the OpenAI-compatible API is unavailable."""
    source_text = text.strip()
    if not source_text:
        return ""
    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={"client": "gtx", "sl": "auto", "tl": "zh-CN", "dt": "t", "q": source_text},
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-News-Bot/1.0)"},
            timeout=8,
        )
        response.raise_for_status()
        body = response.json()
    except Exception:
        return source_text
    try:
        translated = "".join(part[0] for part in body[0] if part and part[0])
    except (KeyError, IndexError, TypeError):
        return source_text
    return translated.strip() or source_text


def translate_to_zh_azure(
    text: str,
    key: str | None,
    region: str | None,
    endpoint: str = "https://api.cognitive.microsofttranslator.com",
) -> str:
    source_text = text.strip()
    if not source_text:
        return ""
    if not key or not region:
        return source_text
    try:
        response = requests.post(
            endpoint.rstrip("/") + "/translate",
            params={"api-version": "3.0", "to": "zh-Hans"},
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Ocp-Apim-Subscription-Region": region,
                "Content-Type": "application/json",
                "X-ClientTraceId": str(uuid4()),
            },
            json=[{"text": source_text}],
            timeout=10,
        )
        response.raise_for_status()
        body = response.json()
        translated = body[0]["translations"][0]["text"]
    except Exception:
        return source_text
    return translated.strip() or source_text


def _volcengine_hmac_sha256(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _volcengine_signing_key(secret_key: str, date: str, region: str, service: str) -> bytes:
    date_key = _volcengine_hmac_sha256(secret_key.encode("utf-8"), date)
    region_key = _volcengine_hmac_sha256(date_key, region)
    service_key = _volcengine_hmac_sha256(region_key, service)
    return _volcengine_hmac_sha256(service_key, "request")


def translate_to_zh_volcengine(
    text: str,
    access_key_id: str | None,
    secret_access_key: str | None,
    region: str = "cn-north-1",
) -> str:
    source_text = text.strip()
    if not source_text:
        return ""
    if not access_key_id or not secret_access_key:
        return source_text

    method = "POST"
    path = "/"
    query = f"Action={VOLCENGINE_TRANSLATE_ACTION}&Version={VOLCENGINE_TRANSLATE_VERSION}"
    body = json.dumps(
        {"TargetLanguage": "zh", "TextList": [source_text]},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    body_hash = hashlib.sha256(body).hexdigest()
    now = datetime.now(timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = now.strftime("%Y%m%d")
    credential_scope = f"{short_date}/{region}/{VOLCENGINE_TRANSLATE_SERVICE}/request"
    canonical_headers = (
        "content-type:application/json\n"
        f"host:{VOLCENGINE_TRANSLATE_HOST}\n"
        f"x-content-sha256:{body_hash}\n"
        f"x-date:{x_date}\n"
    )
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_request = "\n".join(
        [method, path, query, canonical_headers, signed_headers, body_hash]
    )
    string_to_sign = "\n".join(
        [
            "HMAC-SHA256",
            x_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signing_key = _volcengine_signing_key(
        secret_access_key,
        short_date,
        region,
        VOLCENGINE_TRANSLATE_SERVICE,
    )
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "HMAC-SHA256 "
        f"Credential={quote(access_key_id)}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, "
        f"Signature={signature}"
    )
    try:
        response = requests.post(
            f"https://{VOLCENGINE_TRANSLATE_HOST}/?{query}",
            headers={
                "Authorization": authorization,
                "Content-Type": "application/json",
                "Host": VOLCENGINE_TRANSLATE_HOST,
                "X-Content-Sha256": body_hash,
                "X-Date": x_date,
            },
            data=body,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return source_text

    error_payload = (payload.get("ResponseMetadata") or {}).get("Error")
    if error_payload:
        return source_text
    try:
        translated = payload["TranslationList"][0]["Translation"]
    except (KeyError, IndexError, TypeError):
        return source_text
    return translated.strip() or source_text


def translate_to_zh_stable(
    text: str,
    azure_key: str | None = None,
    azure_region: str | None = None,
    volcengine_access_key_id: str | None = None,
    volcengine_secret_access_key: str | None = None,
    volcengine_region: str = "cn-north-1",
) -> str:
    """Translate with Volcengine first, then Azure, then Google's no-key endpoint."""
    source_text = text.strip()
    if not source_text:
        return ""
    translated = translate_to_zh_volcengine(
        source_text,
        access_key_id=volcengine_access_key_id,
        secret_access_key=volcengine_secret_access_key,
        region=volcengine_region,
    )
    if translated and translated != source_text:
        return translated
    translated = translate_to_zh_azure(source_text, key=azure_key, region=azure_region)
    if translated and translated != source_text:
        return translated
    return translate_to_zh_fallback(source_text)
