# 第 5 章：Self-Agent 的协议栈全景与借鉴

> 把前 4 章收口：Self-Agent 的完整协议栈长什么样？哪些地方可以加强？

---

## 5.1 Self-Agent 的协议栈全景

Self-Agent 同时扮演五种角色，形成完整的协议驱动架构：

```
┌─────────────────────────────────────────────┐
│  Self-Agent                                  │
│  ├─ A2A Server（被外部 Agent 调用）           │
│  ├─ A2A Client（delegate_to_agent 调外部）    │
│  ├─ MCP Client（用外部工具）                  │
│  ├─ MCP Server（被外部用工具）                │
│  └─ Skill 容器（封装能力单元）                │
└─────────────────────────────────────────────┘
```

### 各角色对应的代码

| 角色 | 代码 |
|---|---|
| A2A Server | `app/a2a/server.py`（mount_a2a）+ `a2a/executor.py`（SelfAgentExecutor） |
| A2A Client | `app/a2a/client.py`（call_remote_agent）+ delegate_to_agent 工具 |
| MCP Client | `app/mcp/client.py`（MCPClientManager） |
| MCP Server | `app/mcp/server.py`（FastMCP） |
| Skill 容器 | `app/skills/`（skill_registry） |

---

## 5.2 协议栈的数据流

```
外部 Agent
  ↓ A2A 调用本 Agent
SelfAgentExecutor（A2A server）
  ↓ 包装 run_agent
LangGraph 图（agent_node ↔ tools_node）
  ↓ tools_node 执行工具
工具注册表（registry.py）
  ├─ 内置工具（files/shell/plan）
  ├─ MCP 工具（mcp/client.py 发现）
  └─ Skill 工具（skills/ 注册）
  ↓ 或 delegate_to_agent
A2A Client → 外部 Agent
```

无论工具来源（内置/MCP/Skill/外部 Agent），执行路径统一经过 tools_node 的风险分级+审批流水线（全书第 6 章）。**这是注册表统一的价值**。

---

## 5.3 已知限制（诚实声明）

这些是 README 明确列出的当前边界：

| 领域 | 限制 |
|---|---|
| MCP server / Skill | 只能改配置或代码后重启，无运行时增删 |
| A2A 委托 | 无白名单/输出校验（仅超时+错误兜底） |
| Agent Card | 没用于自动路由（靠 LLM 自己猜委托谁） |
| A2A 发现 | 点对点（知道 URL 才能调），无注册中心 |

---

## 5.4 给 Self-Agent 的借鉴建议（汇总）

### 借鉴①：A2A 委托加白名单 + 输出校验（高优先级）

**当前**：delegate_to_agent 只有 60s 超时 + 错误兜底。LLM 能委托任意 URL。

**问题**：
- 安全：LLM 可能被注入，delegate 到恶意 agent
- 质量：外部 agent 返回内容未校验

**改进**：
- 白名单：只允许委托预配置的可信 agent URL
- 输出校验：对委托结果做 schema/内容校验
- 审计：记录所有委托
- 限流：限制委托频率

### 借鉴②：MCP server 运行时增删

**当前**：改 mcp_servers.json 要重启。

**改进**：热加载——运行时增删 server，不中断服务。需要处理「正在用的工具突然消失」的边界情况。

### 借鉴③：Agent Card skills 用于自动路由

**当前**：用户说「翻译」，LLM 自己猜要委托哪个 agent。

**改进**：系统维护已知 agent 的 Card 缓存，根据用户意图查 Card 的 skills 字段，自动找到匹配的 agent。比让 LLM 猜更可靠。

### 借鉴④：MCP 工具风险声明

**当前**：MCP 发现的第三方工具默认按最高风险（EXEC）处理。

**改进**：让 MCP server 在工具元数据里声明风险等级（如 `metadata={"risk": "read"}`）。Self-Agent 的 `_risk_from_metadata()` 已经支持这个机制（全书第 6 章），MCP server 按约定声明即可避免一刀切。

### 借鉴⑤：A2A 注册中心（可选，权衡）

**当前**：点对点（知道 URL 才能调）。

**改进**：agent 启动时注册 Card 到注册中心，client 从注册中心发现。

**权衡**：这牺牲了去中心化（变成中心注册）。如果生态规模小，点对点够用；规模大了才需要注册中心。

---

## 5.5 借鉴优先级

| 借鉴 | 优先级 | 难度 | 收益 |
|---|---|---|---|
| A2A 委托白名单 + 校验 | ★★★ | 低 | 安全大幅增强 |
| MCP 工具风险声明 | ★★ | 低 | 减少不必要审批 |
| Agent Card 自动路由 | ★★ | 中 | 委托更可靠 |
| MCP server 热加载 | ★ | 中 | 运维友好 |
| A2A 注册中心 | ★ | 高 | 规模化发现 |

---

## 5.6 这本书的核心结论

1. **M×N 集成爆炸催生协议**：标准化把点对点变成平台化
2. **MCP 是工具协议**：agent↔tool，工具被动，中心化发现
3. **A2A 是 agent 协议**：agent↔agent，对等体，去中心化发现
4. **两者互补不互斥**：一个 agent 可同时是 MCP client/server + A2A client/server
5. **三层叠加**：function calling → MCP → A2A，不是替代是叠加
6. **Self-Agent 协议栈完整**：五角色齐全，是「协议驱动」Agent 的典型形态
7. **最大改进空间**：A2A 委托的安全（白名单+校验）

---

## 5.7 事实声明

- Self-Agent 协议栈：基于本项目代码 `app/mcp/`、`app/a2a/`、`app/skills/`
- 已知限制：基于 README 明确声明
- 借鉴建议：基于当前实现差距的合理推断

---

→ [回到本书目录](00-总览.md) | [回到书架](../README.md) | [下一本书：自主 Agent 与记忆层](../05-拆解-自主Agent/00-总览.md)
