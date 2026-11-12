"""全局配置：所有可调参数集中在这里，方便演示时改。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("NUDGE_DATA", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "nudge.db"

# 华为云 MaaS（盘古 / DeepSeek）。不配 key 时自动降级为规则抽取器，离线也能跑。
MAAS_BASE_URL = os.getenv("MAAS_BASE_URL", "https://api.deepseek.com").rstrip("/")
MAAS_API_KEY = os.getenv("MAAS_API_KEY", "")
# 线上 /v1/models 实际返回的 id 是 deepseek-flash 与 deepseek-v4-pro；
# 早期写的 deepseek-v4.1-flash 只是口头叫法，不被接口接受（400 model not found）
MAAS_MODEL = os.getenv("MAAS_MODEL", "deepseek-flash")

TZ = "Asia/Shanghai"

# 提醒策略：截止前 N 天
REMIND_DAYS = [7, 3, 1]
# 同一天出现多少个截止算"负载过高"
LOAD_WARN_THRESHOLD = 2
