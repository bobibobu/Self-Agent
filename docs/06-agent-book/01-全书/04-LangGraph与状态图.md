# 第 4 章：LangGraph 与状态图

> 上一章讲了 State 存什么。这章讲**承载 State 流转的那个骨架**：为什么用图不用 while、节点/边/路由/reducer 都是什么。

---

## 4.1 为什么不用 while 写 ReAct 循环

第 1 章那个 ReAct 循环，最直觉的写法是：

```python
while True:
    reply = ask_llm(messages, tools)
    messages.append(reply)
    if not reply.tool_calls:
        break  # 不调工具就结束
    for call in reply.tool_calls:
        result = execute_tool(call)
        messages.append(result)
```

看着挺干净。但一旦你想加这些**生产必需**的能力，就会越写越乱：

1. **状态持久化**：每次循环要把 messages 存下来。存哪？怎么存？崩溃了怎么恢复？
2. **中途暂停**：审批时要停下来问用户。while 循环怎么「暂停」？暂停时状态存哪？
3. **恢复执行**：用户点同意后，怎么从「暂停那一行」继续？
4. **流式输出**：大模型逐字往外吐，怎么实时转发给用户？
5. **并发执行多个工具**：一次返回 3 个 tool_call，怎么并发跑？
6. **可视化**：能不能画个图看看执行到了哪一步？

每一项自己实现都不算难，但**全都要**自己实现，就会变成一坨脆弱的代码。**LangGraph 把这六样打包送给你**，代价是你得学一套「图」的抽象。

这就是 Self-Agent 选 LangGraph 的根本原因——不是图本身多酷，而是图这套抽象**天然适配 Agent 的高阶需求**。

---

## 4.2 状态图的三要素：节点、边、状态

LangGraph 的核心抽象是 **StateGraph（状态图）**。三个要素：

### 节点（Node）—— 干活的函数

每个节点是一个普通的 Python 函数：**接收当前状态，返回部分更新**。

本项目的两个节点：

| 节点 | 函数 | 干什么 | 返回 |
|---|---|---|---|
| `agent` | `agent_node` (`nodes/agent_node.py`) | 问大模型下一步 | `{"messages": [AIMessage]}` |
| `tools` | `tools_node` (`nodes/tools_node.py`) | 执行工具调用 | `{"messages": [ToolMessage...]}` |

注意：节点**只返回变化的部分**，不是整个 state。比如 agent_node 只返回新增的那条 AIMessage，不返回整个 messages 列表。

### 边（Edge）—— 谁连谁

边决定执行顺序。本项目：

```
START → agent          # 一进来先思考
tools → agent          # 动手完，回去思考
```

### 条件边（Conditional Edge）—— 根据情况走哪条路

最关键的一条：agent 节点跑完后，**根据大模型有没有要调工具**，决定下一步：

```python
builder.add_conditional_edges(
    "agent",
    should_use_tools,                          # ← 路由函数
    {"tools": "tools", "end": END},
)
```

`should_use_tools`（`nodes/tools_node.py:202`）的逻辑简单到不能再简单：

```python
def should_use_tools(state) -> str:
    last_msg = state["messages"][-1]
    tool_calls = getattr(last_msg, "tool_calls", None)
    if tool_calls:
        return "tools"
    return "end"
```

看最后一条消息有没有 `tool_calls`。有就去 tools 节点，没有就结束。**这就是 ReAct 循环的「路由器」**——一行 if-else。

---

## 4.3 完整的图组装

`app/agent/graph.py:282` 的 `get_compiled_graph()`，十几行：

```python
async def get_compiled_graph():
    global _compiled_graph
    if _compiled_graph is None:
        with span("graph.compile"):
            checkpointer = await get_checkpointer()
            builder = StateGraph(AgentState)
            builder.add_node("agent", agent_node)
            builder.add_node("tools", tools_node)
            builder.add_edge(START, "agent")
            builder.add_conditional_edges(
                "agent", should_use_tools,
                {"tools": "tools", "end": END},
            )
            builder.add_edge("tools", "agent")
            _compiled_graph = builder.compile(checkpointer=checkpointer)
    return _compiled_graph
```

画成图：

```
START ──→ agent ──┬─(有 tool_calls)─→ tools ──→ agent ...（循环）
                  └─(无 tool_calls)─→ END
```

**整个项目的骨架就是这张图。** 后面所有机制（审批、流式、计划、记忆）都是在这个骨架上加节点、改节点、套包装。

---

## 4.4 Reducer：状态怎么合并（重要但常被忽略）

这是 LangGraph 最容易被忽视、但**至关重要**的概念。

节点只返回「变化部分」（比如一条新消息）。那这条新消息怎么和已有的 messages 列表合并？——靠 **reducer**（合并函数）。

在 `app/agent/state.py`：

```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    plan: NotRequired[Annotated[list[dict], replace_plan]]
```

`Annotated[类型, reducer函数]` 这个语法告诉 LangGraph：「这个字段用这个 reducer 合并」。

### `messages` 用 `add_messages`

LangGraph 内置的 reducer。行为：**追加 + 按 ID 去重**。

- agent_node 返回 `{"messages": [AIMessage(id="x1")]}`
- 已有 messages 是 `[...]`
- 合并后：`[..., AIMessage(id="x1")]`

如果新消息的 ID 和已有的重复，会**替换**而不是追加——这就是去重。

### `plan` 用自定义的 `replace_plan`

```python
def replace_plan(_old: list, new: list) -> list:
    """计划的 reducer：整份替换而不是追加。"""
    return new
```

**为什么 plan 不用 add 而用 replace？** 因为每次 `update_plan` 工具给出的都是**完整的最新计划**（含各步当前状态）。如果用 add 语义，历次快照会堆在一起：第 5 次更新后 plan 里会有 5 份历史计划，毫无意义。

> 🔑 **为什么 reducer 重要**：它决定了「节点返回的变化怎么落到状态上」。用错 reducer（比如 plan 用 add），数据就会错乱。这是图模型比「裸字典 state」严谨的地方——合并语义是显式的、可预测的。

---

## 4.5 Config：给节点传参数的「侧通道」

除了 State，节点还能通过 `config` 收到一些「不进状态的运行时参数」。

本项目这么做的是**系统提示词和工具列表**（见第 3 章）：

```python
config = {
    "configurable": {
        "thread_id": scoped_tid,
        "tools": get_all_tools(),
        "system_prompt": system_prompt,   # 不进 state，走 config
    },
    "recursion_limit": get_settings().agent_recursion_limit,
}
result = await graph.ainvoke({"messages": [HumanMessage(content=message)]}, config=config)
```

节点里这样取：

```python
async def agent_node(state, config, writer):
    configurable = config.get("configurable", {})
    tools = configurable.get("tools", [])
    system_prompt = configurable.get("system_prompt")
```

**为什么用 config 不用 state？** 因为这些东西：
- **每轮可能变**（系统提示含动态检索的记忆/RAG）
- **不需要持久化**（系统提示存进 state 会平方堆积，见第 3 章）
- **不是「对话内容」**（不该出现在 messages 里）

config 是「侧通道」，专门装这类运行时参数。

---

## 4.6 Checkpointer：让图变成「有状态的」

`builder.compile(checkpointer=checkpointer)` 这一行是分水岭。

**没 checkpointer**：图是无状态的，每次 invoke 都从头开始，不能续接、不能中断恢复。

**有 checkpointer**：图在每步后存档，于是：
- 同 `thread_id` 续接（短期记忆）
- `interrupt()` 挂起后能恢复（审批）

checkpointer 的获取见 `app/memory/checkpointer.py:29`，按 `STORAGE_BACKEND` 选 SQLite / Postgres / 内存。

`thread_id` 是 checkpointer 的「会话键」。同一个 thread_id = 同一段对话；换一个 = 新对话。多租户下还会加租户前缀防串（`scoped_thread_id`）。

---

## 4.7 interrupt()：人在回路的基础设施

这是 LangGraph 最「神奇」的能力。

在 tools_node 里，写工具要审批时：

```python
if needs_approval(name):
    decision = interrupt({
        "type": "tool_approval",
        "tool": name,
        "risk": get_risk(name).value,
        "args": args,
        "call_id": call_id,
    })
    # ← 图在这里挂起了，进程可以真的退出
    # 用户决策后用 Command(resume=decision) 续跑，从这里原地返回
```

`interrupt()` 做了什么：

1. 把当前 State 完整存进 checkpointer
2. 抛一个特殊信号让图停止
3. `decision` 还没返回——图挂起了

**进程甚至可以真的退出**。等你（或别的进程）用 `Command(resume=用户的决策)` 续跑：

```python
async for event in resume_agent(thread_id, {"approved": True}):
    ...
```

LangGraph 按 thread_id 读回 State，**从 interrupt() 那一行继续**，`decision` 此时拿到 `{"approved": True}`，工具才真正执行。

> ⚠️ **一个踩过的坑**：拿到 `approval_required` 事件就 `break` 退出循环，会导致中断状态**还没写进 checkpointer**就被中止，之后 resume 什么也不做且不报错。所以事件流**必须消费完**。`tests/test_local_mode.py` 有回归测试钉住这一点。

---

## 4.8 recursion_limit：防止死循环

图有环（agent → tools → agent），理论上可能无限转。

`recursion_limit` 限制图最多执行多少步（节点调用次数）。本项目配置项 `AGENT_RECURSION_LIMIT`，本地模式默认 80，服务端 25。

撞上限制会抛 `RecursionError`，表现为「任务跑到一半停了」。这是有意的——防止模型陷入「调同一个工具 → 失败 → 再调」的死循环烧 token。

---

## 4.9 流式：custom + updates 双模式

LangGraph 的流式输出有点特殊。本项目用**两种 stream_mode 组合**（`graph.py:435`）：

```python
async for chunk in graph.astream(
    graph_input, config=config,
    stream_mode=["custom", "updates"],
    version="v2",
):
```

- **`custom`**：节点里用 `writer({...})` 主动推的事件。agent_node 逐 token 推文本、tools_node 推工具事件，都走这个。
- **`updates`**：节点跑完后的状态增量。用来检测 `__interrupt__`（审批挂起）和兜底抓 AIMessage 文本。

`version="v2"` 是新的统一格式：每个 chunk 是 `{"type", "ns", "data"}` 的字典（v1 是元组）。

这就是真·token 流式的基础——大模型每吐一个字，agent_node 就 `writer({"type":"token","text":字})` 推出去，前端实时收到。

---

## 4.10 一个细节：单例 + 预热

`get_compiled_graph()` 是**单例**（`_compiled_graph` 全局变量）。第一次调用时编译，之后复用。

但第一次编译要连 Postgres 建连接池——DB 不可用时要等满超时（默认 5 秒），这段时间会算在**第一个请求**头上。

所以 `app/main.py` 的 lifespan 里有**预热**：应用启动时就调一次 `get_compiled_graph()`，让这个成本发生在启动期而不是真实用户请求上。trace 里能直接看到「第一次请求为什么慢」——就是那个 `graph.compile` span。

---

## 4.11 外部世界怎么做

| 框架 | 怎么编排 |
|---|---|
| **LangGraph**（本项目） | 状态图，channel+reducer+checkpointer，最严谨 |
| **OpenAI Agents SDK** | 轻量 Agent 循环（model↔tools），不做图的抽象 |
| **LlamaIndex Workflows** | **事件驱动**：用 event + handler 组织流程，不是图节点 |
| **AutoGen v0.4** | **事件驱动 + 异步**运行时，消息驱动多 agent |
| **CrewAI** | **流程驱动**：sequential / hierarchical 内置流程 |
| **MetaGPT** | **SOP 流程驱动**：把人类工作流程固化成剧本 |

四种编排哲学：**图驱动 / 事件驱动 / 流程驱动 / 协议驱动**（Self-Agent 的 MCP+A2A 属于协议驱动）。详见拆解②。

---

## 4.12 面试一句话

> **Q：为什么用 LangGraph 不用 while？**
> A：while 写的 ReAct 循环要自己实现状态持久化、中断恢复、流式、并发工具，全做完很脆弱。LangGraph 用图抽象把这些打包提供，代价是学一套图概念，但换来工业级的可恢复性和可观测性。

> **Q：reducer 是干什么的？**
> A：节点只返回状态变化，reducer 决定怎么把这个变化合并进状态。比如 messages 用 add_messages（追加+去重），plan 用 replace_plan（整份替换）。用错 reducer 数据会错乱。

下一章：LLM 抽象层——怎么用一套代码调三家模型。

→ [第 5 章：LLM 多协议抽象](05-LLM多协议抽象.md)
