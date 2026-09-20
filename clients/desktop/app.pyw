"""Self-Agent 桌面客户端 —— 无控制台入口（pythonw 执行本文件，双击即用）。

逻辑全部在 app.py 里；本文件只负责以 run_name='__main__' 复用它。
双击运行的前提是 .pyw 关联到 pythonw.exe（Windows 官方解释器默认行为）。
"""

import os
import runpy
import sys

sys.dont_write_bytecode = True
runpy.run_path(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py"),
    run_name="__main__",
)
