# Self-Agent 桌面客户端

类 ZCode / Codex 的桌面形态：**选一个项目目录 → 在原生窗口里与编码 Agent 干活**。

```
┌────────────────────────────────────┐
│ pywebview 原生窗口（WebView2）      │
│  └─ 内嵌 React 前端（FastAPI 托管） │
├────────────────────────────────────┤
│ FastAPI 后端（同进程后台线程）      │
│  ├─ 编码 Agent（LangGraph 1.x）     │
│  ├─ 文件/Shell 工具 + 审批闸门      │
│  └─ SQLite 存储（零外部依赖）       │
└────────────────────────────────────┘
```

## 启动

```bash
# 在仓库根目录
uv run python clients/desktop/app.py
```

| 参数 | 说明 |
|---|---|
| `--workspace DIR` | 指定工作区（缺省弹目录选择框） |
| `--approval MODE` | `gated`（默认，写/执行前确认）· `auto` · `strict` · `readonly` |
| `--port N` | 后端端口（缺省自动挑空闲端口） |
| `--no-window` | 不开窗口只起后端（调试/CI） |

LLM key 优先读环境变量 `GLM_API_KEY`，其次仓库根目录 `.env`。

## 窗口里能做什么

- 流式对话：任务拆解、执行、汇报全程可见（工具调用步骤实时展示）
- **审批弹窗**：Agent 要写文件/执行命令时弹确认框，展示工具名、风险等级与完整参数
- **任务计划面板**：Agent 维护的多步计划实时打勾
- 工具列表：内置编码工具 + MCP 发现的工具（见根目录 `mcp_servers.json.example`）

## 依赖说明

- `pywebview`（已加入 uv 依赖）：Windows 上走 Edge WebView2，Win10/11 自带；
  缺失或不可用时自动退回默认浏览器打开同一页面，功能不变
- 无需 Docker / 数据库：SQLite 按工作区分库存放对话状态
  （`~/.local/share/selfagent/projects/<项目哈希>/state.db`）
