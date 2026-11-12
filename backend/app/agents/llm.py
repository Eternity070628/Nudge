"""LLM 客户端：默认指向 DeepSeek，OpenAI 兼容接口。

Key 优先级：页面设置（SQLite）> 环境变量 MAAS_API_KEY。
没有 Key 时返回 None，让 extractor 自动降级到规则抽取。
"""
from __future__ import annotations

import json
import os
import urllib.request

from .. import config, db

# 部署在受限网络（如 PythonAnywhere 免费帐号）时可强制走规则引擎
off = os.getenv("NUDGE_DISABLE_LLM", "").strip().lower()
_disabled = off in ("1", "true", "yes", "on")


def current() -> tuple[str, str, str]:
    """返回 (base_url, model, api_key)；页面设置覆盖环境变量。"""
    saved = db.get_settings()
    base = (saved.get("base_url") or config.MAAS_BASE_URL).rstrip("/")
    model = saved.get("model") or config.MAAS_MODEL
    key = saved["api_key"] if "api_key" in saved else config.MAAS_API_KEY
    return base, model, key


def current_model() -> str:
    return current()[1]


def available() -> bool:
    if _disabled:
        return False
    base, _, key = current()
    return bool(base and key)


def disable() -> None:
    """评测时强制规则模式，保证结果可复现。"""
    global _disabled
    _disabled = True


def chat(system: str, user: str, temperature: float = 0.0, timeout: int = 60) -> str | None:
    """调用 OpenAI 兼容接口。失败返回 None，不抛异常。"""
    if _disabled:
        return None
    base, model, key = current()
    if not base or not key:
        return None
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    request = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None