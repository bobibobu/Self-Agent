"""打开桌面窗口连接到已运行的后端（带品牌图标注入）。

用法：python clients/desktop/window.py [url]
缺省 url = http://127.0.0.1:8899/
"""

import contextlib
import ctypes
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8899/"
ICON = Path(__file__).resolve().parent / "icon.ico"


def _hwnd_from_native(native):
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


def _set_icon(hwnd: int) -> None:
    if sys.platform != "win32" or not ICON.exists():
        return
    user32 = ctypes.windll.user32
    hb = user32.LoadImageW(None, str(ICON), 1, 64, 64, 0x10)
    hs = user32.LoadImageW(None, str(ICON), 1, 16, 16, 0x10)
    if hb:
        user32.SendMessageW(hwnd, 0x80, 1, hb)  # WM_SETICON ICON_BIG
    if hs:
        user32.SendMessageW(hwnd, 0x80, 0, hs)  # WM_SETICON ICON_SMALL
    with contextlib.suppress(Exception):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("self.agent.desktop")
    print("ICON INJECTED", flush=True)
class WindowApi:
    """暴露给前端 window.pywebview.api 的窗口控制（无边框标题栏用）。"""

    def __init__(self, w=None):
        self._w = w

    def set_window(self, w):
        self._w = w

    def minimize(self):
        self._w.minimize()

    def maximizeToggle(self):
        # pywebview 没有 toggle；用窗口尺寸标记近似（够用：最大化↔还原）
        import ctypes

        hwnd = _hwnd_from_native(getattr(self._w, "native", None))
        if hwnd and sys.platform == "win32":
            # 判断当前是否最大化（screen 宽高+偏移）
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


win_api = WindowApi()
window = webview.create_window(
    "Self-Agent", URL,
    width=1280, height=860, min_size=(960, 640),
    background_color="#0b0e14",
    frameless=True,
    js_api=win_api,
)
win_api.set_window(window)


def inject():
    for _ in range(300):  # WebView2 首次初始化可能很慢，给足 30 秒
        hwnd = _hwnd_from_native(getattr(window, "native", None))
        if hwnd:
            _set_icon(hwnd)
            return
        time.sleep(0.1)
    print("ICON TIMEOUT: window.native 未就绪", flush=True)


threading.Thread(target=inject, daemon=True).start()
webview.start()
