#!/usr/bin/env python3
"""Nudge 桌面启动器：安装版入口。

- 把数据库、日志、配置放到用户数据目录，不写安装目录；
- 启动本地 uvicorn 服务并自动打开浏览器；
- 提供一个很小的控制窗口（打开 Nudge / 退出）；
- 支持 --check 供 CI 做冒烟测试。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_TITLE = "Nudge · 校园截止管家"


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".nudge-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def user_data_dir() -> Path:
    override = os.getenv("NUDGE_DATA")
    if override:
        return Path(override)
    home = Path.home()
    if sys.platform == "win32":
        bases = [os.getenv("LOCALAPPDATA"), os.getenv("APPDATA")]
        candidates = [Path(base) / "Nudge" for base in bases if base]
    elif sys.platform == "darwin":
        candidates = [home / "Library" / "Application Support" / "Nudge"]
    else:
        candidates = [Path(os.getenv("XDG_DATA_HOME", home / ".local" / "share")) / "nudge"]
    candidates.append(home / "Nudge")
    candidates.append(Path(sys.executable).resolve().parent / "NudgeData")
    candidates.append(Path(tempfile.gettempdir()) / "Nudge")
    for candidate in candidates:
        if writable_dir(candidate):
            return candidate
    raise RuntimeError("找不到可写的数据目录，请设置 NUDGE_DATA 指向可写路径")


def setup_environment():
    root = bundle_root()
    data = user_data_dir()
    data.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NUDGE_DATA", str(data))
    os.environ["NUDGE_PACKAGED"] = "1"

    static = None
    for candidate in (root / "backend" / "app" / "static", root / "app" / "static"):
        if candidate.is_dir():
            static = candidate
            break
    if static is None:
        raise RuntimeError("找不到前端静态资源目录")
    os.environ["NUDGE_STATIC"] = str(static)

    backend = root / "backend"
    if backend.is_dir():
        sys.path.insert(0, str(backend))
    return root, data, static


def setup_logging(data_dir: Path) -> None:
    try:
        handlers = [logging.FileHandler(data_dir / "nudge.log", encoding="utf-8")]
        if sys.stderr is not None and sys.stderr.isatty():
            handlers.append(logging.StreamHandler())
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            handlers=handlers,
            force=True,
        )
    except Exception:
        logging.basicConfig(level=logging.INFO)


def local_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def health(port: int):
    try:
        with local_opener().open(f"http://127.0.0.1:{port}/api/health", timeout=0.5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def find_running():
    for port in range(8000, 8011):
        data = health(port)
        if data and data.get("app") == "nudge":
            return port
    return None


def choose_port(preferred: int) -> int:
    for port in range(preferred, preferred + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"端口 {preferred}–{preferred + 29} 都被占用")


def wait_until_ready(port: int, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if health(port):
            return True
        time.sleep(0.25)
    return False


def open_browser(url: str, no_browser: bool) -> None:
    if no_browser:
        return
    try:
        if not webbrowser.open(url):
            logging.warning("自动打开浏览器失败，请手动访问 %s", url)
    except Exception:
        logging.exception("自动打开浏览器失败")


def run_gui(server, url: str, data_dir: Path, no_browser: bool) -> int:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        logging.warning("Tkinter 不可用，改为无界面运行")
        return run_headless(server, url, no_browser)

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("500x240")
    root.minsize(460, 220)
    root.resizable(False, False)

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=APP_TITLE, font=("", 16, "bold")).pack(anchor="w")
    ttk.Label(frame, text="本地服务已启动，数据只保存在这台电脑。").pack(anchor="w", pady=(6, 0))
    link = ttk.Label(frame, text=url, foreground="#d97706")
    link.pack(anchor="w", pady=(10, 0))
    ttk.Label(frame, text=f"数据目录：{data_dir}", foreground="#6b7280").pack(anchor="w", pady=(6, 0))

    actions = ttk.Frame(frame)
    actions.pack(anchor="w", pady=(18, 0))

    def shutdown():
        server.should_exit = True
        root.after(200, root.destroy)

    def open_web():
        open_browser(url, False)

    ttk.Button(actions, text="打开 Nudge", command=open_web).pack(side="left")
    ttk.Button(actions, text="退出", command=shutdown).pack(side="left", padx=(10, 0))
    root.protocol("WM_DELETE_WINDOW", shutdown)
    root.after(300, lambda: open_browser(url, no_browser))
    try:
        root.mainloop()
    finally:
        server.should_exit = True
    return 0


def run_headless(server, url: str, no_browser: bool) -> int:
    print(f"[Nudge] 服务地址：{url}", flush=True)
    print("[Nudge] 按 Ctrl+C 退出", flush=True)
    open_browser(url, no_browser)
    try:
        while server.started is False and not server.should_exit:
            time.sleep(0.1)
        while not server.should_exit:
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.should_exit = True
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    root, data_dir, static_dir = setup_environment()
    setup_logging(data_dir)
    logging.info("Nudge 启动：bundle=%s data=%s static=%s", root, data_dir, static_dir)

    running = find_running()
    if running:
        logging.info("已有 Nudge 实例运行在端口 %s", running)
        open_browser(f"http://127.0.0.1:{running}", args.no_browser)
        return 0

    from app.main import app as fastapi_app
    import uvicorn

    if args.check:
        print(f"Nudge {fastapi_app.version}")
        print(f"data={data_dir}")
        print(f"static={static_dir}")
        return 0

    port = choose_port(args.port)
    url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(
        fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        log_config=None,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="nudge-server", daemon=True)
    thread.start()

    if not wait_until_ready(port):
        raise RuntimeError(f"服务启动超时，请检查日志：{data_dir / 'nudge.log'}")
    logging.info("Nudge 已就绪：%s", url)
    if args.headless:
        return run_headless(server, url, args.no_browser)
    return run_gui(server, url, data_dir, args.no_browser)


def write_crash_log(exc: BaseException) -> None:
    path = Path(tempfile.gettempdir()) / "nudge-crash.log"
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {exc!r}\n")
    except Exception:
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as error:
        logging.exception("Nudge 启动失败")
        write_crash_log(error)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(APP_TITLE, f"启动失败：\n{error}\n\n崩溃日志：{Path(tempfile.gettempdir()) / 'nudge-crash.log'}")
            root.destroy()
        except Exception:
            pass
        sys.exit(1)