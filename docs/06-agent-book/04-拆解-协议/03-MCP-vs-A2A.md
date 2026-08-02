# 第 3 章：MCP vs A2A —— 工具 vs Agent

> 这是面试最常考的对比。把 MCP 和 A2A 拉到一张表上，看清本质区别。
> 结论：**互补不互斥**，一个 Agent 可同时是两者。

---

## 3.1 一句话区分

- **MCP**：agent ↔ **工具**。工具是**被动**的，没有自主决策。
- **A2A**：agent ↔ **agent**。双方都**对等**，都有 LLM/记忆/工具，各自自主。

---

## 3.2 详细对比表

| 维度 | MCP | A2A |
|---|---|---|
| 通信方 | agent ↔ **工具** | agent ↔ **agent** |
| 对方性质 | 被动（无自主决策） | **对等**（都有 LLM/记忆/工具） |
| 类比 | USB-C（工具接口） | HTTP（服务器互通） |
| 发现方式 | host 主动连 server（中心化） | `/.well-known/agent-card.json`（去中心化，DNS 式） |
| 传输 | stdio / streamable-http | JSON-RPC over HTTP + SSE |
| 数据模型 | Tools / Resources / Prompts | Task / Message / Part |
| 工作单元 | 一次工具调用 | 一个 Task（有状态机） |
| 透明度 | 透明（client 知道工具 schema） | 不透明（只看输入输出） |
| 提出方 | Anthropic（2024） | Google → Linux Foundation（2025） |

---

## 3.3 为什么互补不互斥

MCP 管 **agent 怎么用工具**，A2A 管 **agent 怎么找别的 agent**。两者解决不同层面的问题。

### 一个完整场景

```
用户：「帮我翻译这段话，然后查一下相关 GitHub issue」
  ↓
本 Agent（A2A client）：delegate_to_agent 给翻译 Agent（A2A）
  ↓                          ← A2A：agent ↔ agent
翻译 Agent（A2A server + MCP client）：
  ├─ 用 MCP 调「translate」工具（来自某个 MCP server）  ← MCP：agent ↔ tool
  └─ 返回译文
  ↓
本 Agent（MCP client）：用 MCP 调「search_issues」工具  ← MCP：agent ↔ tool
  ↓
整合翻译 + issue 结果，回复用户
```

这里本 Agent 同时是 A2A client（委托翻译）+ MCP client（查 issue）。翻译 Agent 是 A2A server（被委托）+ MCP client（用翻译工具）。

---

## 3.4 一个 Agent 的四种角色

Self-Agent 同时扮演：

```
┌─────────────────────────────────────────────┐
│  Self-Agent                                  │
│  ├─ A2A Server（被外部 Agent 调用）           │
│  ├─ A2A Client（delegate_to_agent 调外部）    │
│  ├─ MCP Client（用外部工具）                  │
│  └─ MCP Server（被外部用工具）                │
└─────────────────────────────────────────────┘
```

这就是「协议驱动」的 Agent——不靠单一框架，靠标准协议接入生态。

---

## 3.5 边界：什么时候用 MCP，什么时候用 A2A

### 用 MCP 当...

- 你要给 agent 加一个**工具**（搜索、查数据库、调 API）
- 工具是**被动**的（给它参数它返回结果）
- 工具没有自己的 LLM/记忆

### 用 A2A 当...

- 你要让 agent 和**另一个 agent** 协作
- 对方有**自主决策**能力（它自己有 LLM/工具）
- 你不需要知道对方内部怎么工作

### 模糊地带

有时候分不清。比如「让另一个 agent 帮我翻译」——翻译 agent 是「工具」还是「agent」？

判断标准：**对方有没有自主决策能力**。
- 如果翻译就是一个确定性函数（输入文本 → 输出译文），用 MCP
- 如果翻译 agent 自己要决定「这段用什么风格翻」「要不要查术语库」，用 A2A

---

## 3.6 发现机制的差异（中心化 vs 去中心化）

### MCP：中心化发现

Host **主动配置**要连哪些 server（`mcp_servers.json`）。Server 不主动宣布自己的存在。

```
Host 配置 mcp_servers.json → 连 server → 发现工具
```

### A2A：去中心化发现

Agent **主动暴露** Agent Card 在 `/.well-known/`。任何人都能来发现。

```
任意 client → GET /.well-known/agent-card.json → 发现 agent
```

### 为什么不同

- MCP 的工具是 host 私有的（host 决定用哪些），中心化配置合理
- A2A 的 agent 是开放生态（任何人都能调用），去中心化发现更合适

---

## 3.7 给 Self-Agent 的启示

Self-Agent 已经同时用 MCP 和 A2A，设计是对的。这章主要是**理解两者的边界和配合**。

### 一个设计原则

**优先用 MCP（工具），需要 agent 自主性时才用 A2A**。因为：
- MCP 更轻（工具是被动函数调用）
- A2A 更重（要管 Task 状态机、Card、对方 agent 的不确定性）

能工具解决的就工具，需要对方自主决策才 delegate 给 agent。

---

## 3.8 事实声明

- 对比基于第 1、2 章已声明的官方资料
- 边界判断是基于「对方有没有自主性」的合理框架

→ [下一章：演进脉络](04-演进脉络.md)
