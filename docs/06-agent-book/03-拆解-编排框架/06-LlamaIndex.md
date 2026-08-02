# 第 6 章：LlamaIndex Workflows —— 事件驱动

> 以 RAG/数据索引起家，2025 推出 Workflows 1.0——**事件驱动、async-first** 的多步编排。
> 在「检索增强记忆」上最成熟——毕竟它是 RAG 起家的。

---

## 6.1 它是什么

地址 github.com/run-llama/llama_index（大仓库，star 数未单独统计 Workflows）。2025 推出 **Workflows 1.0**——轻量、**事件驱动、async-first** 的多步 agent 编排框架。还有 **Agentic Document Workflows (ADW)** 针对文档场景。

---

## 6.2 核心设计

### ① 事件驱动

用 **event + handler** 组织流程，而非图节点：

```python
from llama_index.core.workflow import Workflow, step, Event

class MyWorkflow(Workflow):
    @step
    async def step_a(self, ev: StartEvent) -> EventB:
        # 收到 StartEvent，处理后发出 EventB
        ...

    @step
    async def step_b(self, ev: EventB) -> EventC:
        # 收到 EventB，处理后发出 EventC
        ...
```

每个 handler 监听某种 event，处理后发出新 event，触发下游 handler。

### ② async-first

全异步设计，天然适合 IO 密集的 agent（调 LLM、检索、调工具都是 IO）。

### ③ 强 RAG/检索底子

LlamaIndex 是 RAG/数据索引起家的，**检索和索引是其长项**。Workflows 继承了这层能力。

---

## 6.3 ★ 三种编排哲学对比

| 维度 | LangGraph（图） | LlamaIndex（事件） | Self-Agent（协议） |
|---|---|---|---|
| 组织方式 | 节点+边+路由 | event+handler | MCP+A2A 协议 |
| 流程显式度 | **高**（图可视化） | 中（event 流隐式） | 低（协议不管流程） |
| 状态管理 | channel+reducer（严谨） | event 传递 | checkpointer |
| 异步 | 支持 | **原生 async** | 支持 |
| 适合 | 复杂状态、需中断恢复 | IO 密集、解耦流程 | 跨框架协作 |

### 事件驱动 vs 图驱动

- **图驱动（LangGraph）**：流程是显式的图，可可视化、可中断恢复。状态严谨。
- **事件驱动（LlamaIndex）**：流程是 event 流，handler 之间解耦。异步天然。

图驱动更适合「需要严格控制流程和状态」的场景（Self-Agent 的审批）；事件驱动更适合「流程灵活、IO 密集」的场景。

---

## 6.4 LlamaIndex 在检索增强记忆上的优势

因为 RAG 起家，LlamaIndex 在「检索增强记忆」上最成熟：
- 多种索引类型（向量、关键词、图、树）
- 多种检索策略（语义、关键词、混合）
- 文档加载/分块/向量化全流程成熟

**对比 Self-Agent**：Self-Agent 的 RAG 是简化版（复用 PostgresStore 的语义索引，全书第 11 章）。如果要更强的 RAG，LlamaIndex 的检索底子最成熟。

---

## 6.5 给 Self-Agent 的借鉴

### 借鉴①：更强的 RAG/记忆检索

Self-Agent 的长期记忆用单跳语义检索（top-3）。如果要做更复杂的（多跳、混合检索、图检索），LlamaIndex 的检索引擎值得借鉴或直接集成。

### 借鉴②：事件驱动作为流程补充

Self-Agent 的核心是图驱动（LangGraph）。某些 IO 密集的辅助流程（如多源检索并发）可以用事件驱动模式补充。但这会引入两套范式，权衡要慎重。

---

## 6.6 事实声明

- Workflows 1.0、事件驱动、ADW：LlamaIndex 官方博客
- 检索能力：基于 LlamaIndex 长期 RAG 定位

→ [下一章：多 Agent 四范式对比](07-四范式对比.md)
