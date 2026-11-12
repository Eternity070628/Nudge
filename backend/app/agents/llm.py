"""LLM 客户端：有 Key 走华为云 MaaS，没有就返回 None，让上层降级到规则抽取。

刻意不用任何第三方 SDK，只用标准库，保证评委机器上能跑。
"""
from __future__ import annotations

import json
import urllib.request

from ..config import MAAS_API_KEY, MAAS_BASE_URL, MAAS_MODEL


def available() -> bool:
    return bool(MAAS_API_KEY and MAAS_BASE_URL)


def chat(system: str, user: str, temperature: float = 0.0, timeout: int = 60) -> str | None:
    """调用 OpenAI 兼容接口。失败返回 None，不抛异常。"""
    if not available():
        return None
    payload = {
        "model": MAAS_MODEL,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    req = urllib.request.Request(
        MAAS_BASE_URL + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + MAAS_API_KEY,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception:
        return None
