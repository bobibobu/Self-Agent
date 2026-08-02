# 第 1 章：LangGraph —— 状态图（本项目内核）

> LangChain 团队的「低层级 Agent 编排框架」，专解「长时运行、有状态、可中断、可恢复」。
> Self-Agent 的编排引擎就是它，所以这章最重要——理解 LangGraph 内部，就能理解 Self-Agent 内核为什么这么设计。

---

## 1.1 它是什么

地址 github.com/langchain-ai/langgraph，~38.6k star（调研时点，待核实）。是 Self-Agent 编排引擎的直接对标物。

定位：**低层级（low-level）Agent 编排框架**。不是「开箱即用的 agent」，而是「让你能自己搭出可控 agent 的积木」。

---

## 1.2 五个核心设计思想（来自 Building LangGraph 工程博客）

### ① 放弃 DAG，拥抱循环图

早期 LangChain 的 Chain 是 DAG（有向无环图），但 Agent 必须「思考→行动→观察」**循环**。DAG 表达不了循环。

LangGraph 基于 **Pregel/BSP（Bulk Synchronous Parallel）算法**——Google Pregel 图计算论文的思路：每一「超步（superstep）」内并发执行就绪节点，超步结束统一合并状态。**天然支持环和并发**。

### ② StateGraph + Channels + Reducers

状态不是黑盒字典，而是由若干命名的 **channel** 组成。每个 channel 有：
- **版本号**：跟踪变化
- **reducer**（合并函数）：多节点并发写同一 channel 时决定怎么合并

Self-Agent 的 `messages` 用 `add_messages`、`plan` 用 `replace_plan` 就是 reducer（全书第 4 章详讲）。

这是比「裸字典 state」严谨得多的状态模型——合并语义是显式的、可预测的。

### ③ Checkpointer = 持久化 + 容错 + 中断

每次超步把序列化后的 channel 值（默认 MsgPack，支持加密）、版本号、节点消费进度写入 checkpointer（SQLite/Postgres/Redis）。

这让 Agent：
- 崩溃后从任意 checkpoint 恢复
- 跨机器恢复
- interrupt() 挂起后跨进程续跑

Self-Agent 的审批机制（全书第 8 章）就建立在 checkpointer 之上。

### ④ interrupt() = HITL 基础设施

`interrupt()` 依赖 checkpointer 把执行挂起，进程可以真正退出内存。等用户输入后用新的 invoke 从 checkpoint 续跑。

支持：
- **time-travel**：回到历史节点重跑
- **reject**：拒绝某步动作

这是工业级 HITL（人在回路）的范本。Self-Agent 的审批闸门用它实现「图挂起→用户决策→原地继续」。

### ⑤ provider-agnostic + 可部署

配合 LangGraph Platform/Cloud 做部署，支持流式、队列、Cron 等。

---

## 1.3 Self-Agent 怎么用 LangGraph

Self-Agent 是 LangGraph 的典型用法：

| LangGraph 能力 | Self-Agent 用法 |
|---|---|
| StateGraph | 两个节点（agent/tools）+ 条件路由 = ReAct |
| channel + reducer | messages（add_messages）/ plan（replace_plan） |
| checkpointer | 短期记忆 + 中断恢复 |
| interrupt() | 审批闸门 |
| astream + custom/updates | 真·token 流式 |

详见全书第 4 章。

---

## 1.4 为什么 Self-Agent 选 LangGraph

回顾全书第 4 章：用 `while` 写 ReAct 循环，要自己实现状态持久化、中断恢复、流式、并发工具，全做完很脆弱。LangGraph 用图抽象把这些打包提供，代价是学一套图概念，但换来工业级的可恢复性和可观测性。

**Self-Agent 选 LangGraph 的根本原因**：要图的状态严谨性。如果项目简单（不需要中断恢复/复杂状态），OpenAI SDK 的轻原语更易上手。

---

## 1.5 ★ LangGraph 的内部机制（深入）

这部分帮你看懂 Self-Agent 内核「为什么这么写」。

### Pregel 超步模型

LangGraph 的执行是「超步」驱动的：
1. 一个超步内，所有就绪节点**并发执行**
2. 超步结束，统一收集所有节点的输出，按 reducer 合并进 channel
3. 根据边决定下一超步哪些节点就绪
4. 重复，直到没有就绪节点（END）

这就是为什么 Self-Agent 的 tools_node 能并发执行多个 tool_call——Pregel 模型天然支持。

### channel 的版本号

每个 channel 有版本号。checkpointer 存的不只是「当前值」，是「每个 channel 在每个超步的值」。这让 time-travel 成为可能——回到任意超步的状态。

### reducer 解决竞态

多个节点并发写同一 channel 会竞态。reducer 显式定义合并规则：
- `add_messages`：追加 + 按 ID 去重
- `replace_plan`：整份替换
- 自定义：任意合并逻辑

没有 reducer，并发写会数据错乱。这是 LangGraph 比「裸字典 state」严谨的核心。

### interrupt() 的实现

`interrupt()` 不是普通的「暂停」。它：
1. 把当前 State 完整存进 checkpointer（标记为 interrupted）
2. 抛特殊信号让图停止
3. 进程可以真退出
4. `Command(resume=...)` 续跑时，从 checkpointer 读回 State，从 interrupt 那行继续

这是为什么 Self-Agent 的审批能「跨进程恢复」——状态在 checkpointer 里，不依赖进程存活。

---

## 1.6 ⚠️ 安全提示

2025 年 11 月 Check Point 披露了 SQLite/Redis checkpointer 的 **RCE 漏洞链**——反序列化攻击。

Self-Agent 用的是 SQLite/Postgres，自查注意：
- 不要加载来源不明的 checkpoint 数据
- 关注 LangGraph 安全更新
- 反序列化是 checkpointer 的固有风险面

---

## 1.7 LangGraph 的代价

选 LangGraph 不是免费的：

1. **学习曲线陡**：channel/reducer/checkpointer/interrupt 概念多
2. **耦合 LangChain 消息类型**：State 必须用 LangChain 的 AnyMessage，Self-Agent 不得不加 bridge.py 翻译层（全书第 5 章）
3. **失去 LangSmith 自动追踪**：自研 LLM 抽象后，用结构化日志 + trace_id 补偿
4. **checkpointer 反序列化风险**：上面的安全提示

---

## 1.8 给 Self-Agent 的启示

Self-Agent 已经用 LangGraph，所以这章主要是「理解为什么」。但有几个点值得注意：

1. **channel + reducer 是好设计**：如果未来加更多状态字段，都要配 reducer，不能裸字典
2. **interrupt 是 HITL 基础设施**：审批、人审、time-travel 都靠它，值得深挖
3. **关注 checkpointer 安全**：反序列化风险要盯

---

## 1.9 事实声明

- 五个设计思想：Building LangGraph 工程博客（langchain.com/blog/building-langgraph）
- ~38.6k star 待核实
- RCE 漏洞：Check Point 2025-11 披露
- 内部机制描述基于官方文档 + 工程博客推断

→ [下一章：OpenAI Agents SDK](02-OpenAI-SDK.md)
