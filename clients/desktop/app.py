"""
Self-Agent 桌面客户端启动器
===========================
对标 ZCode / Codex 的桌面形态：选一个项目目录 → 原生窗口里与编码 Agent 干活。

架构：
    ┌────────────────────────────────────┐
    │ pywebview 原生窗口（WebView2）      │
    │  └─ 加载 http://127.0.0.1:<port>/  │
    │      （内嵌 React 前端，FastAPI 托管）│
    ├────────────────────────────────────┤
    │ FastAPI 后端（本进程内线程）        │
    │  ├─ 编码 Agent（LangGraph 1.x）     │
    │  ├─ 文件/Shell 工具 + 审批闸门      │
    │  └─ SQLite 存储（本地单机，零依赖）  │
    └────────────────────────────────────┘

本地形态默认：STORAGE_BACKEND=sqlite（免四个数据库）、AUTH_ENABLED=false
（单用户）。LLM key 优先环境变量，其次仓库根目录 .env。

用法：
    python clients/desktop/app.py                 # 弹目录选择框
    python clients/desktop/app.py --workspace D:/proj
    python clients/desktop/app.py --no-window     # 不开窗口（服务器/调试）
    python clients/desktop/app.py --approval auto # 跳过审批（沙箱/CI）

依赖：pywebview（可选，缺了自动退回默认浏览器打开）。
"""

from __future__ import annotations

import argparse
import contextlib
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

_started = threading.Event()


def pick_workspace(tk_fallback: bool = True) -> str:
    """选工作区：优先原生目录选择框（tkinter），失败退回命令行输入/当前目录。"""
    if tk_fallback:
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(title="选择 Agent 的工作区（项目目录）")
            root.destroy()
            if path:
                return str(Path(path).resolve())
        except Exception:
            pass  # 无显示环境/tkinter 缺失时走下面的输入
    try:
        raw = input("工作区目录（回车=当前目录）: ").strip()
    except EOFError:
        raw = ""
    return str(Path(raw).resolve()) if raw else str(Path.cwd())


def free_port(preferred: int = 0) -> int:
    """取一个可绑定端口。preferred>0 时优先探测它。"""
    if preferred:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", preferred)) != 0:
                return preferred
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_backend(port: int, timeout: float = 30.0) -> bool:
    """轮询 /api/health 直到后端就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def start_backend(port: int) -> None:
    """在本进程的守护线程里跑 uvicorn（应用内嵌，不是子进程）。"""
    import uvicorn

    from app.core.eventloop import PG_LOOP_FACTORY
    from app.core.logging import get_logger
    from app.main import app  # 必须在环境变量设置完之后 import（Settings 会缓存）

    logger = get_logger("selfagent.desktop")

    # 不指定 loop 时 uvicorn 在 Windows 上选 ProactorEventLoop，psycopg 异步不支持它，
    # 登录、会话列表、对话历史持久化会全部失效。改用 Selector（见 app/core/eventloop.py）。
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", loop=PG_LOOP_FACTORY)
    logger.info("内嵌后端启动：127.0.0.1:%d（loop=%s）", port, PG_LOOP_FACTORY)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _started.set()


def _hwnd_from_native(native) -> int | None:
    """从 pywebview 的 window.native 取 Win32 句柄。

    Windows 后端（winforms）里 native 是 Form 对象，句柄在 .Handle 属性；
    其他平台/后端可能直接就是 int。
    """
    if native is None:
        return None
    if isinstance(native, int):
        return native
    handle = getattr(native, "Handle", None)
    if handle is not None:
        try:
            return int(handle)
        except (TypeError, ValueError):
            return None
    try:
        return int(native)
    except (TypeError, ValueError):
        return None


def _set_window_icon(hwnd: int, icon_path: Path) -> None:
    """给原生窗口注入自定义图标（标题栏 + 任务栏）。

    pywebview 在 Windows 上不支持 icon 参数（WebView2 后端），任务栏会显示
    python.exe 的默认图标。这里直接走 Win32：LoadImageW 从 .ico 加载句柄，
    SendMessageW 发 WM_SETICON（大图标 = 任务栏/Alt-Tab，小图标 = 标题栏）。
    失败静默（图标只是面子，不能因为它炸掉主流程）。
    """
    if sys.platform != "win32" or not icon_path.exists():
        return
    try:
        import ctypes

        hwnd = int(hwnd)
        IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
        WM_SETICON, ICON_SMALL, ICON_BIG = 0x80, 0, 1
        user32 = ctypes.windll.user32
        hicon_big = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 64, 64, LR_LOADFROMFILE)
        hicon_small = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        # 任务栏分组身份（不设的话按 pythonw.exe 归组）
        with contextlib.suppress(Exception):
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("self.agent.desktop")
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 窗口图标设置失败（不影响使用）：{e}")


class WindowApi:
    """暴露给前端 window.pywebview.api 的窗口控制（无边框标题栏用）。"""

    def __init__(self, w=None):
        self._w = w

    def set_window(self, w):
        """create_window 之前就要把 api 传进去，窗口对象建好后回填。"""
        self._w = w

    def minimize(self):
        self._w.minimize()

    def maximizeToggle(self):
        import ctypes

        hwnd = _hwnd_from_native(getattr(self._w, "native", None))
        if hwnd and sys.platform == "win32":
            user32 = ctypes.windll.user32
            placement = ctypes.create_string_buffer(60)
            if user32.GetWindowPlacement(hwnd, placement):
                state = int.from_bytes(placement.raw[12:16], "little")
                if state == 2:  # SW_SHOWMAXIMIZED
                    self._w.restore()
                    return
        self._w.maximize()

    def close(self):
        self._w.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="Self-Agent 桌面客户端")
    parser.add_argument("--workspace", default="", help="工作区目录（缺省弹选择框）")
    parser.add_argument("--port", type=int, default=0, help="后端端口（缺省自动分配）")
    parser.add_argument("--approval", default="gated",
                        choices=["auto", "gated", "strict", "readonly"],
                        help="工具审批策略（默认 gated：写与执行前询问）")
    parser.add_argument("--no-picker", action="store_true", help="不弹目录选择框（无交互环境）")
    parser.add_argument("--no-window", action="store_true", help="不开窗口，只起后端（调试/CI）")
    args = parser.parse_args()

    # 1) 工作区：编码 Agent 的文件/Shell 工具都被禁闭在这个目录里
    workspace = args.workspace or (pick_workspace() if sys.stdin.isatty() and not args.no_picker else str(Path.cwd()))
    ws = Path(workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)

    # 2) 环境变量：先吃仓库 .env（key 等），再强制本地单机形态的覆盖项
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    os.environ["WORKSPACE_ROOT"] = str(ws)
    os.environ["STORAGE_BACKEND"] = "sqlite"
    os.environ["AUTH_ENABLED"] = "false"
    os.environ.setdefault("OTEL_ENABLED", "false")

    port = free_port(args.port)
    start_backend(port)
    if not wait_backend(port):
        print("❌ 后端启动超时", file=sys.stderr)
        return 1

    url = f"http://127.0.0.1:{port}/"
    print(f"✅ Self-Agent 桌面客户端\n   工作区: {ws}\n   地址:   {url}")
    print("   （关闭窗口或按 Ctrl+C 退出）")

    if args.no_window:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    # 3) 原生窗口；pywebview 不可用则退回默认浏览器
    icon_path = Path(__file__).resolve().parent / "icon.ico"
    try:
        import webview  # noqa: PLC0415

        win_api = WindowApi()
        window = webview.create_window(
            "Self-Agent", url,
            width=1280, height=860, min_size=(960, 640),
            background_color="#0b0e14",  # 与前端主题一致，避免启动白闪
            frameless=True,              # 无系统边框：前端自绘标题栏（拖拽 + 窗口控制）
            js_api=win_api,              # 前端标题栏的最小化/最大化/关闭走这里
        )
        win_api.set_window(window)

        def _on_loaded():
            # 窗口句柄就绪后注入品牌图标（pywebview Windows 后端不支持 icon 参数）。
            # func 在 GUI 循环启动后调用，但 Form 可能还没建好，轮询兜底
            for _ in range(300):
                hwnd = _hwnd_from_native(getattr(window, "native", None))
                if hwnd:
                    _set_window_icon(hwnd, icon_path)
                    return
                time.sleep(0.1)

        try:
            webview.start(func=_on_loaded)
        except TypeError:
            # 旧版 pywebview 无 func 参数：起线程轮询句柄
            import threading as _threading

            def _poll_icon():
                # WebView2 首次初始化可能很慢，给足 30 秒
                for _ in range(300):
                    hwnd = _hwnd_from_native(getattr(window, "native", None))
                    if hwnd:
                        _set_window_icon(hwnd, icon_path)
                        return
                    time.sleep(0.1)

            _threading.Thread(target=_poll_icon, daemon=True).start()
            webview.start()
    except Exception as e:
        print(f"⚠️ 原生窗口不可用（{e}），改用默认浏览器打开")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
