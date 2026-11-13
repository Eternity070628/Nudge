"""全局配置：所有可调参数集中在这里，方便演示时改。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent      # backend/
REPO_DIR = BASE_DIR.parent                              # 仓库根


def _load_env(path: Path) -> None:
    """极简 .env 读取：KEY=VALUE，# 开头是注释；已存在的环境变量优先。

    这样本地把 .env 放进仓库根目录就能跑，PythonAnywhere 上仍可用环境变量面板，
    两边行为一致，也不用引入第三方依赖。
    """
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


for _candidate in (REPO_DIR / ".env", BASE_DIR / ".env"):
    _load_env(_candidate)

DATA_DIR = Path(os.getenv("NUDGE_DATA", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "nudge.db"

# 华为云 MaaS（盘古 / DeepSeek）。不配 key 时自动降级为规则抽取器，离线也能跑。
MAAS_BASE_URL = os.getenv("MAAS_BASE_URL", "https://api.deepseek.com").rstrip("/")
MAAS_API_KEY = os.getenv("MAAS_API_KEY", "")
# 线上 /v1/models 实际返回的 id 是 deepseek-flash 与 deepseek-v4-pro；
# 早期写的 deepseek-v4.1-flash 只是口头叫法，不被接口接受（400 model not found）
MAAS_MODEL = os.getenv("MAAS_MODEL", "deepseek-flash")

# ---------------------------------------------------------------------------
# 邮箱验证码：Microsoft Graph 委托授权，验证码由 GRAPH_SENDER 本人邮箱发出。
# 不需要邮箱密码，也不需要 SMTP：2024-09 起 Outlook 已停用 SMTP 基本认证，
# 走 Graph（HTTPS 443）才能真发信。凭据只在本机生成，不进仓库。
# ---------------------------------------------------------------------------
# 默认租户 consumers = 个人 Microsoft 账户；公司/学校账户填自己的 tenant id 或域名
GRAPH_TENANT_ID = os.getenv("GRAPH_TENANT_ID", "consumers")
# 默认客户端是微软官方发布的公共客户端「Microsoft Graph Command Line Tools」，
# 它已允许设备码流（公共客户端），个人 MSA 也能授权，因此不必自己注册 Entra 应用。
# 有自己的应用注册时用 GRAPH_CLIENT_ID 覆盖即可。
GRAPH_CLIENT_ID = os.getenv("GRAPH_CLIENT_ID", "14d82eec-204b-4c2f-b7e8-296a70dab67e")
GRAPH_SENDER = os.getenv("GRAPH_SENDER", "Eternity070628@outlook.com")
GRAPH_SCOPES = os.getenv("GRAPH_SCOPES", "https://graph.microsoft.com/Mail.Send offline_access")
# 已经完成过授权时，可把 refresh token 放进环境变量，启动时自动写入本机 SQLite，
# 适合部署到服务器：数据库是临时的，环境变量才是持久的。
GRAPH_REFRESH_TOKEN = os.getenv("GRAPH_REFRESH_TOKEN", "").strip()
# 开发模式：没有可用凭据时把验证码回显到页面/日志，并明确标注「未真实发信」
NUDGE_EMAIL_DEV = os.getenv("NUDGE_EMAIL_DEV", "").strip().lower() in ("1", "true", "yes", "on")

TZ = "Asia/Shanghai"

# 提醒策略：截止前 N 天
REMIND_DAYS = [7, 3, 1]
# 同一天出现多少个截止算"负载过高"
LOAD_WARN_THRESHOLD = 2
