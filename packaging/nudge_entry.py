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
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

APP_TITLE = "Nudge · 校园截止管家"

LOADING_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
html,body{height:100%;margin:0;background:#fff7ed;color:#7c2d12;
font-family:-apple-system,BlinkMacSystemFont,"Microsoft YaHei",sans-serif}
.wrap{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px}
.logo{font-size:28px;font-weight:700;letter-spacing:.5px}
.tip{font-size:13px;color:#9a3412}
.dot{display:inline-block;width:6px;height:6px;margin:0 3px;border-radius:50%;
background:#f97316;animation:b 1s infinite}
.dot:nth-child(2){animation-delay:.15s}.dot:nth-child(3){animation-delay:.3s}
@keyframes b{0%,80%,100%{opacity:.25;transform:translateY(0)}40%{opacity:1;transform:translateY(-4px)}}
</style></head><body><div class="wrap"><div class="logo">Nudge</div>
<div class="tip">正在启动本地服务<span class="dot"></span><span class="dot"></span><span class="dot"></span></div>
</div></body></html>"""

ERROR_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>html,body{height:100%;margin:0;background:#fff7ed;color:#7c2d12;
font-family:-apple-system,BlinkMacSystemFont,"Microsoft YaHei",sans-serif}
.wrap{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px}
b{font-size:18px}.tip{font-size:13px;color:#9a3412;max-width:520px;text-align:center;line-height:1.6}
</style></head><body><div class="wrap"><b>启动超时</b>
<div class="tip">本地服务没有在预期时间内就绪。请关闭窗口后重新打开；仍失败请查看数据目录下的 nudge.log。</div>
</div></body></html>"""


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
    if getattr(sys, "frozen", False):
        # 安装版默认接入现有 PythonAnywhere 中心；管理端保存的地址可覆盖它
        os.environ.setdefault("NUDGE_CENTRAL_URL", "https://eternity0628.pythonanywhere.com")

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
        with local_opener().open(f"http://127.0.0.1:{port}/api/health", timeout=0.2) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def find_running(data_dir: Path | None = None):
    """优先信任实例文件，避免逐个端口等超时导致启动慢。"""
    if data_dir is not None:
        try:
            state = json.loads((data_dir / "instance.json").read_text(encoding="utf-8"))
            port = int(state.get("port") or 0)
            if port and health(port):
                return port
        except Exception:
            pass
    for port in range(8000, 8010):
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
    ttk.Label(frame, text="关闭窗口只会最小化，服务继续运行；要退出请点「退出」。",
              foreground="#6b7280").pack(anchor="w", pady=(6, 0))

    actions = ttk.Frame(frame)
    actions.pack(anchor="w", pady=(18, 0))

    def shutdown():
        server.should_exit = True
        root.after(200, root.destroy)

    def open_web():
        open_browser(url, False)

    ttk.Button(actions, text="打开 Nudge", command=open_web).pack(side="left")
    ttk.Button(actions, text="退出", command=shutdown).pack(side="left", padx=(10, 0))
    root.protocol("WM_DELETE_WINDOW", root.iconify)
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


_runtime: dict = {"window": None, "tray": None, "tray_ready": False}


def asset_path(name: str) -> Path:
    for base in (bundle_root() / "assets", bundle_root() / "packaging" / "assets"):
        path = base / name
        if path.is_file():
            return path
    return bundle_root() / "assets" / name


def focus_existing(data_dir: Path) -> bool:
    """已有实例在跑时，让它的窗口回到前台，而不是再开一个新的。"""
    try:
        state = json.loads((data_dir / "instance.json").read_text(encoding="utf-8"))
        control = int(state.get("control"))
    except Exception:
        return False
    try:
        with socket.create_connection(("127.0.0.1", control), timeout=1.2) as sock:
            sock.sendall(b"focus\n")
            return sock.recv(16).startswith(b"ok")
    except OSError:
        return False


def start_focus_channel(data_dir: Path, on_focus, app_port: int = 0) -> int:
    """监听本机唤起请求；再次双击图标时把已有窗口提到前台。"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    port = server.getsockname()[1]
    try:
        (data_dir / "instance.json").write_text(
            json.dumps({"port": app_port, "control": port}), encoding="utf-8"
        )
    except OSError:
        logging.warning("无法写入 instance.json，再次双击不会唤起已有窗口")

    def loop():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            try:
                command = conn.recv(64).decode("utf-8", "replace").strip()
                if command.startswith("focus"):
                    on_focus()
                    conn.sendall(b"ok")
            except OSError:
                pass
            finally:
                conn.close()

    threading.Thread(target=loop, name="nudge-focus", daemon=True).start()
    return port


def start_tray(window, server, restore) -> None:
    """托盘常驻：关闭窗口只是隐藏，托盘菜单可重新打开或退出。"""
    try:
        import pystray
        from PIL import Image

        image = Image.open(asset_path("nudge.png"))
    except Exception:
        logging.exception("托盘组件不可用，关闭窗口将直接退出应用")
        return

    def quit_app(icon, _item):
        icon.stop()
        server.should_exit = True
        try:
            window.destroy()
        except Exception:
            logging.exception("关闭窗口失败")

    menu = pystray.Menu(
        pystray.MenuItem("打开 Nudge", lambda _icon, _item: restore(), default=True),
        pystray.MenuItem("退出", quit_app),
    )
    icon = pystray.Icon("nudge", image, APP_TITLE, menu)
    _runtime["tray"] = icon

    def serve():
        _runtime["tray_ready"] = True
        try:
            icon.run()
        except Exception:
            logging.exception("托盘启动失败，关闭窗口改为退出应用")
            _runtime["tray_ready"] = False

    threading.Thread(target=serve, name="nudge-tray", daemon=True).start()


def close_soon(window, delay: float = 4.0) -> None:
    time.sleep(delay)
    try:
        window.destroy()
    except Exception:
        pass


def run_app(server, url: str, data_dir: Path, no_browser: bool,
            window_check: bool = False) -> int:
    """浏览器套壳：一个原生窗口承载界面，任务栏显示独立的 Nudge 进程。"""
    try:
        import webview
    except Exception:
        logging.warning("未安装 pywebview，回退到浏览器模式")
        return run_gui(server, url, data_dir, no_browser)

    window = webview.create_window(
        APP_TITLE, html=LOADING_HTML, width=1200, height=780, min_size=(900, 620),
    )
    _runtime["window"] = window

    def boot():
        port = urllib.parse.urlparse(url).port or 80
        if not wait_until_ready(port):
            logging.error("服务启动超时：%s", url)
            try:
                window.load_html(ERROR_HTML)
            except Exception:
                pass
            return
        logging.info("Nudge 已就绪：%s", url)
        try:
            window.load_url(url)
        except Exception:
            logging.exception("加载页面失败")

    threading.Thread(target=boot, name="nudge-boot", daemon=True).start()

    def restore():
        try:
            window.show()
            window.restore()
            window.on_top = True
            window.on_top = False
        except Exception:
            logging.exception("恢复窗口失败")

    def on_closing():
        if _runtime.get("tray_ready") and not window_check:
            window.hide()
            return False
        server.should_exit = True
        return True

    window.events.closing += on_closing
    start_focus_channel(data_dir, lambda: restore(), urllib.parse.urlparse(url).port or 80)
    if not window_check:
        start_tray(window, server, restore)
    else:
        threading.Thread(target=close_soon, args=(window,), daemon=True).start()
    try:
        webview.start()
    except Exception:
        logging.exception("套壳启动失败，回退到浏览器模式")
        tray = _runtime.get("tray")
        if tray:
            try:
                tray.stop()
            except Exception:
                pass
        wait_until_ready(urllib.parse.urlparse(url).port or 80)
        return run_gui(server, url, data_dir, no_browser)
    server.should_exit = True
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--window-check", action="store_true")
    args = parser.parse_args(argv)

    root, data_dir, static_dir = setup_environment()
    setup_logging(data_dir)
    logging.info("Nudge 启动：bundle=%s data=%s static=%s", root, data_dir, static_dir)

    running = find_running(data_dir)
    if running:
        logging.info("已有 Nudge 实例运行在端口 %s", running)
        if not focus_existing(data_dir):
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

    if args.headless:
        return run_headless(server, url, args.no_browser)
    return run_app(server, url, data_dir, args.no_browser, args.window_check)


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