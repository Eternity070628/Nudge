"""LLM 客户端：默认指向 DeepSeek，OpenAI 兼容接口。

开关优先级：页面设置里的 llm_mode（model / rules / auto）> 环境变量 NUDGE_DISABLE_LLM。
Key 优先级：页面设置（SQLite）> 环境变量 MAAS_API_KEY。

为什么要两层开关：部署到只允许白名单出网的环境（比如 PythonAnywhere 免费帐号）时，
环境变量会先把 LLM 关掉保守起跑；但用户在页面「模型设置」里存了 Key，就说明他要真调模型，
这时以页面为准，否则线上永远是规则引擎，页面上的输入框等于摆设。

没有任何 Key 时 chat() 返回 None，extractor 自动降级到规则抽取。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from .. import config, db

# 部署在受限网络时可强制走规则引擎；页面保存 Key 后会被 llm_mode=model 覆盖
off = os.getenv("NUDGE_DISABLE_LLM", "").strip().lower()
_disabled = off in ("1", "true", "yes", "on")

# 最近一次失败的原因，/api/health 与 /api/llm-test 用它回答「为什么没调起来」
_last: dict[str, Any] = {"ok": None, "status": 0, "error": "", "at": ""}


def current() -> tuple[str, str, str]:
    """返回 (base_url, model, api_key)；页面设置覆盖环境变量。"""
    saved = db.get_settings()
    base = (saved.get("base_url") or config.MAAS_BASE_URL).rstrip("/")
    model = saved.get("model") or config.MAAS_MODEL
    key = saved["api_key"] if "api_key" in saved else config.MAAS_API_KEY
    return base, model, key


def current_model() -> str:
    return current()[1]


def mode() -> str:
    """model / rules / auto —— 页面里显式选过的模式。"""
    try:
        return (db.get_settings().get("llm_mode") or "").strip().lower()
    except Exception:
        return ""


def available() -> bool:
    base, _, key = current()
    wanted = mode()
    if wanted == "rules":
        return False
    if wanted == "model":
        return bool(base and key)
    return (not _disabled) and bool(base and key)


def disable() -> None:
    """评测时强制规则模式，保证结果可复现。"""
    global _disabled
    _disabled = True


def last_error() -> dict[str, Any]:
    return dict(_last)


def _record(ok: bool, status: int, error: str = "") -> None:
    global _last
    _last = {
        "ok": ok,
        "status": status,
        "error": error[:400],
        "at": datetime.now().isoformat(timespec="seconds"),
    }


def proxy() -> str:
    """出网代理：环境变量优先；PythonAnywhere 的 web 进程里没有 proxy 环境变量，但必须走它的代理。"""
    for name in ("NUDGE_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    if os.getenv("DOMAIN_SOCKET") or os.getenv("PA_DOMAIN"):
        return "http://proxy.server:3128"
    return ""


def _opener() -> urllib.request.OpenerDirector:
    addr = proxy()
    if addr:
        handler = urllib.request.ProxyHandler({"http": addr, "https": addr})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


def _request(url: str, key: str, payload: dict[str, Any] | None, timeout: int) -> dict[str, Any]:
    """发一次请求，把 HTTP 状态码和响应体原样带回来，不做静默吞异常。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + key,
        },
        method="POST" if data else "GET",
    )
    opener = _opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            _record(True, response.status)
            return {"ok": True, "status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:
            pass
        _record(False, exc.code, body or str(exc.reason))
        return {"ok": False, "status": exc.code, "body": body, "error": str(exc.reason)}
    except Exception as exc:  # URLError / 超时 / DNS：把原话留给页面看
        _record(False, 0, str(exc))
        return {"ok": False, "status": 0, "body": "", "error": str(exc)}


def chat(system: str, user: str, temperature: float = 0.0, timeout: int = 60) -> str | None:
    """调用 OpenAI 兼容接口。失败返回 None，不抛异常，但会记下 last_error。"""
    if not available():
        return None
    base, model, key = current()
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    result = _request(base + "/chat/completions", key, payload, timeout)
    if not result["ok"]:
        return None
    try:
        return json.loads(result["body"])["choices"][0]["message"]["content"]
    except Exception as exc:
        _record(False, result["status"], "响应不是预期的 chat/completions 结构：" + str(exc))
        return None


def probe(kind: str = "chat", timeout: int = 30) -> dict[str, Any]:
    """给页面「测试连接」用：真发一次最小请求，把状态码和报错原文摊开。"""
    base, model, key = current()
    if not base:
        return {"ok": False, "reason": "no_base_url", "model": model}
    if not key:
        return {"ok": False, "reason": "no_key", "model": model, "base": base}
    if kind == "models":
        result = _request(base + "/models", key, None, timeout)
    else:
        payload = {
            "model": model,
            "temperature": 0.0,
            "max_tokens": 64,
            "messages": [
                {"role": "system", "content": "只输出一个汉字：好。不要思考过程，不要解释。"},
                {"role": "user", "content": "ping"},
            ],
        }
        result = _request(base + "/chat/completions", key, payload, timeout)
    out = {
        "ok": result["ok"],
        "status": result["status"],
        "model": model,
        "base": base,
        "kind": kind,
        "proxy": proxy().split("//")[-1],
    }
    if result["ok"]:
        body = result.get("body", "")
        try:
            data = json.loads(body)
            if kind == "models":
                out["models"] = [m.get("id") for m in data.get("data", [])][:40]
            else:
                choice = data["choices"][0]
                message = choice.get("message", {})
                text = message.get("content") or message.get("reasoning_content") or ""
                out["reply"] = text.strip()[:200]
                out["finish_reason"] = choice.get("finish_reason", "")
        except Exception:
            out["body"] = body[:300]
    else:
        out["error"] = result.get("error", "")
        out["body"] = (result.get("body") or "")[:400]
    return out
