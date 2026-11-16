"""桌面端 ↔ 中心的事件同步。

策略：本机把所有有效事件与删除墓碑推给中心，中心按 dedup_key 做 last-write-wins
合并后，返回 since 之后的增量；本机再把增量应用到本地。失败只记日志，不影响本地操作。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from .. import db
from . import central

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_last_sync = 0.0
MIN_INTERVAL = 30.0


def enabled() -> bool:
    return central.enabled()


def push_pull(user_id: str) -> dict[str, Any] | None:
    """推送本机事件并拉取中心增量；返回本次应用的条数。"""
    if not enabled():
        return None
    token = central.session_token(user_id)
    if not token:
        return None
    with _lock:
        since = db.get_user_settings(user_id).get("sync_since", "")
        local = db.export_sync(user_id)
        try:
            result = central.sync_events(token, since, local["events"], local["deleted"])
        except central.CentralError as error:
            _log.warning("事件同步失败：%s", error)
            return None
        applied = 0
        for event in result.get("events") or []:
            if db.apply_sync_event(user_id, event):
                applied += 1
        for item in result.get("deleted") or []:
            key = item.get("dedup_key") or ""
            if db.apply_sync_delete(user_id, key, item.get("updated_at") or ""):
                applied += 1
        now = result.get("now") or ""
        if now:
            db.save_user_settings(user_id, {"sync_since": now})
    return {"applied": applied}


def schedule(user_id: str) -> None:
    """页面活动时触发一次后台同步，30 秒内不重复。"""
    if not enabled():
        return

    def run():
        global _last_sync
        wait = MIN_INTERVAL - (time.time() - _last_sync)
        if wait > 0:
            return
        _last_sync = time.time()
        push_pull(user_id)

    threading.Thread(target=run, daemon=True).start()


def start_loop() -> None:
    """后台兜底：每 60 秒同步一次本机所有已绑定中心的用户。"""
    if not enabled():
        return

    def loop():
        while True:
            time.sleep(60)
            try:
                for user in db.list_users():
                    if user.get("central_id"):
                        push_pull(user["id"])
            except Exception:
                _log.exception("定时事件同步失败")

    threading.Thread(target=loop, name="nudge-sync", daemon=True).start()