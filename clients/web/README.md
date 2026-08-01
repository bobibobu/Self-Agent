# Self-Agent Web 前端

React + Vite 实现的聊天界面，接后端 SSE 流式接口，支持：
- 真·token 级流式输出（打字机效果）
- 工具调用过程实时展示（"正在调用 get_weather..."）
- 多会话切换（不同 thread_id）
- 用户切换（体验记忆/画像个性化）

## 快速开始

```bash
# 1. 先启动后端（项目根目录）
cd ../../
uv run uvicorn app.main:app --reload

# 2. 启动前端
cd clients/web
npm install
npm run dev
# → 打开 http://localhost:5173
```

## 工作原理

```
浏览器 ──fetch POST──→ /chat/stream (SSE)
         ReadableStream     ↓
         逐块解析 event    后端 LangGraph stream_chat
```

因为 `/chat/stream` 是 POST（带 body），浏览器原生 EventSource 只支持 GET，
所以用 `fetch + ReadableStream` 手动解析 SSE 文本流（见 `src/api.js`）。

## 事件类型

| 事件 | 说明 |
|---|---|
| `token` | LLM 逐 token 文本，实时拼接到气泡 |
| `tool_calls` | Agent 决定调用工具 |
| `tool_start` | 工具开始执行 |
| `tool_result` | 工具返回结果 |
| `done` | 完成，附完整回复 |
| `error` | 错误 |

## 生产部署

```bash
npm run build    # 产物在 dist/
```

可被后端托管（FastAPI 挂载静态文件），或独立部署（配 `VITE_API_BASE` 环境变量指向后端地址）。

## 配置

- 后端地址：开发时通过 vite proxy（`/api` → `localhost:8000`），见 `vite.config.js`
- 生产：设环境变量 `VITE_API_BASE=https://your-api.com`
