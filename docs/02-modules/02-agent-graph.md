# LangGraph Agent 编排

> 讲清楚 Self-Agent 的 Agent 是怎么用 LangGraph 搭起来的：状态图、节点、路由、短期记忆。

---

## 一、为什么用 LangGraph？

LangGraph 把 Agent 抽象成一张**状态图（StateGraph）**：

- **状态（State）** 在节点间流转，每步可持久化（→ 短期记忆）
- **节点（Node）** 是处理函数（调 LLM、执行工具、路由）
- **边（Edge）** 决定流转方向，支持条件分支（→ ReAct 循环）

相比直接写 `while` 循环的 Agent，LangGraph 提供：
- 内置的状态持久化（checkpointer）→ 天然支持多轮对话、断点续跑
- 可视化图结构 → 调试清晰
- 人机协同（interrupt）→ Phase 后续接入
- 子图与多 Agent 编排 → Phase 4

---

## 二、ReAct 循环设计

ReAct = **Re**asoning + **Act**ing：模型先思考要不要用工具，要用就调用，拿到结果再思考。

```
START → [agent节点] ──┬── 有 tool_calls ──→ [tools节点] ──→ [agent节点]
                      │                                        (循环)
                      └── 无 tool_calls ──→ END
```

### 状态定义（`app/agent/state.py`）

```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
```

- `messages`：完整对话历史
- `add_messages` 是 reducer：节点返回新消息时**自动追加并按 ID 去重**

### 三个核心组件

| 组件 | 文件 | 职责 |
|---|---|---|
| agent 节点 | `nodes/agent_node.py` | 调 LLM，返回 AIMessage（可能带 tool_calls） |
| tools 节点 | `nodes/tools_node.py` | 执行 tool_calls，返回 ToolMessage |
| 条件路由 | `nodes/tools_node.py:should_use_tools` | 判断是否进 tools 节点 |
| 桥接 | `nodes/bridge.py` | LangChain 消息 ↔ 统一 LLM 模型互转 |

---

## 三、为什么手写 ReAct 而不用 create_react_agent？

LangGraph 提供 `create_react_agent(model, tools)` 一行搞定，但它**强制要求 LangChain ChatModel**。
我们用自研 LLM 抽象层（非 ChatModel），所以手写图——好处是：

- 完全掌控消息格式转换（通过 bridge.py）
- 工具执行可定制（错误处理、日志、未来接 MCP）
- 流式输出可精确控制

代价：多写了约 50 行图组装代码。值得。

---

## 四、短期记忆接入

```python
# app/agent/graph.py
compiled = builder.compile(checkpointer=await get_checkpointer())
```

- 后端选择由 `STORAGE_BACKEND` 决定（`auto` 为默认）：优先 `AsyncPostgresSaver`（Postgres 持久化、跨进程共享），连不上自动回退 `MemorySaver`（进程内，重启丢失，启动日志有 WARNING）
- CLI 本地模式显式设为 `sqlite`（`~/.local/share/selfagent/projects/<工作区哈希>/state.db`，按工作区分库）

调用时通过 `thread_id` 区分会话：
```python
config = {"configurable": {"thread_id": "user-123-session-1"}}
await graph.ainvoke({"messages": [...]}, config)
```

**同一个 thread_id 自动恢复历史消息**，实现多轮上下文。换 thread_id 就是新对话。

---

## 五、工具系统

工具用 `langchain_core.tools.tool` 装饰器定义：

```python
@tool
def get_weather(city: str) -> str:
    """查询城市天气。"""
    ...
```

装饰器自动从**函数签名 + docstring** 生成给 LLM 的 function schema。
LLM 看到 schema 就知道：有什么工具、各自干嘛、参数怎么传。

schema 转换在 `nodes/bridge.py` 的 `build_tool_definitions()`，结果**按工具缓存**
（key = name + description + schema 类）：工具注册表运行期基本静态，而 Pydantic 的
`model_json_schema()` 是纯 CPU 反射遍历——不缓存的话每次 LLM 调用都要重算全部
工具的 schema，实测占 /chat 热路径近两成 CPU（14 个工具）。换了 schema 类
（如 MCP 重建工具）缓存自动失效。注意 key 不能用 `type(args_schema)`——所有
Pydantic 模型的元类都是同一个 `ModelMetaclass`，起不到区分作用
（`tests/test_perf_optimizations.py` 锁此行为）。

工具注册表（`app/agent/registry.py`）是工具列表的**单一真相来源**，运行时共 14 个：
- 内置基础（`app/agent/tools/__init__.py`，共 3 个）：`calculator`（AST 解析的安全数学求值）、`get_current_time`（时区时间）、`get_weather`（演示用模拟数据）
- 编码工具（`app/agent/tools/files.py` / `shell.py`，`CODING_TOOLS_ENABLED=true` 时注册）：`read_file` / `list_dir` / `glob_files` / `grep_files` / `write_file` / `edit_file` / `delete_file` / `run_command`
- 任务计划（`app/agent/plan.py`）：`update_plan` —— 维护多步任务待办清单（存在图状态里）
- Skill 工具（`app/skills/builtin.py`）：`advanced_math` —— 高精度/符号数学
- A2A 协作（`app/a2a/client.py`）：`delegate_to_agent` —— 把任务委托给其他 Agent

另有 MCP 工具在运行时从外部 MCP server 发现后动态注册（见 MCP 模块文档）。

工具通过 `config["configurable"]["tools"]` 在运行时注入，避免编译期绑定。

---

## 六、防死循环

```python
config = {"recursion_limit": get_settings().agent_recursion_limit}
# 服务端默认 25，CLI 本地模式 80（编码任务循环更多）
```

限制 agent↔tools 循环次数，防止模型反复调用工具不收敛。
