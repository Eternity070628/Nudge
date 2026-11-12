"""PythonAnywhere WSGI 入口：把 FastAPI(ASGI) 包成 WSGI 交给 mod_wsgi。

PythonAnywhere 的 WSGI 配置文件只需要三行 loader，真正的启动逻辑留在这里，
这样 git push 之后 touch 本文件即可重载。
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
os.environ.setdefault("NUDGE_DATA", str(REPO / "backend" / "data"))
# 免费帐号出网有白名单，DeepSeek/MaaS 大概率连不上；设 0 可强制打开 LLM
os.environ.setdefault("NUDGE_DISABLE_LLM", "1")

from a2wsgi import ASGIMiddleware  # noqa: E402
from app.main import app  # noqa: E402

application = ASGIMiddleware(app)

