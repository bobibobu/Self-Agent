# 第 2 章：OpenAI Agents SDK —— handoffs + guardrails

> OpenAI 官方生产级 Agent SDK，是 2024 教学项目 Swarm 的继任者。
> 「少抽象、强原语、和 OpenAI 模型深度绑定」。

---

## 2.1 它是什么

地址 github.com/openai/openai-agents-python，~18k star（2025 年 3 月建仓，增长极快）。是 2024 教学性项目 **Swarm** 的继任者——Swarm 是「概念演示」，Agents SDK 是「生产级」。

定位哲学：**少抽象、强原语**。不给一堆隐藏行为的「魔法」，给几个清晰可组合的原语。

---

## 2.2 五个可组合原语

### ① Agents

LLM + 指令 + 工具 + guardrails 的封装。最基本的单元。

### ② ★ Handoffs（核心概念）

Agent 之间**显式转交控制权**。这是 Swarm 留下的核心概念。

```python
# Agent A 可以 handoff 到 Agent B
agent_a = Agent(
    name="客服",
    handoffs=[agent_b],  # 客服可以把控制权交给 agent_b
)
```

**handoff 是「控制权转移」，不是「调用」**：
- handoff：A 把整个对话控制权交给 B，**A 退出，B 接管**，上下文随之迁移
- 调用（如 Self-Agent 的 delegate_to_agent）：A 委托 B 做一件事，拿到结果，**A 继续**

语义不同：handoff 是「接力」，delegate 是「派工单」。

### ③ ★ Guardrails（一等公民）

可配置的**输入/输出安全校验**，可堆叠：
- prompt injection 检测
- PII（个人身份信息）过滤
- 鉴权
- 任意自定义校验

```python
agent = Agent(
    ...,
    input_guardrails=[injection_detector, auth_check],
    output_guardrails=[pii_filter],
)
```

**很多框架把安全当可选，OpenAI 把 guardrails 做进核心原语**——这是值得借鉴的位置设计。

### ④ Sessions

会话/记忆状态管理。

### ⑤ Tracing

内置可观测性，直接进 OpenAI Dashboard。

---

## 2.3 两种多 Agent 模式

- **Agents-as-tools**：编排器把子 agent 当工具调（子 agent 的输出回到编排器）
- **Handoffs**：显式转交控制权（子 agent 接管，编排器退出）

---

## 2.4 ★ handoff 的踩坑点

handoff 走**自己的管线**，**工具级 guardrails 不作用于 handoff 调用本身**。

这是个常见陷阱：你以为给所有路径都加了 guardrail，但 handoff 这条路径绕过了它。生产使用要特别注意。

---

## 2.5 哲学对比：OpenAI 轻原语 vs LangGraph 重框架

| 维度 | OpenAI Agents SDK | LangGraph |
|---|---|---|
| 抽象层级 | 轻原语（几个清晰概念） | 重框架（图/channel/reducer） |
| 学习曲线 | 低 | 高 |
| 灵活度 | 中（原语组合） | 高（图任意描述） |
| 状态严谨性 | 中（Sessions） | **高（channel+reducer+checkpoint）** |
| 适合 | 简单 agent、快速上手 | 复杂状态、需中断恢复 |

**Self-Agent 选 LangGraph** 因为要图的状态严谨性（中断恢复、checkpointer）。如果项目简单，OpenAI SDK 的轻原语更易上手。

---

## 2.6 给 Self-Agent 的借鉴

### 借鉴①：guardrails 作为一等公民

Self-Agent 的安全主要在工具层（风险分级+审批+沙箱）。可以借鉴 OpenAI，把**输入/输出校验**做成可堆叠的原语：
- 输入：prompt injection 检测、敏感信息过滤
- 输出：PII 过滤、有害内容检测

放在 agent_node 的入口/出口，不依赖工具层。

### 借鉴②：handoff vs delegate 的语义区分

Self-Agent 的 `delegate_to_agent` 是 delegate（A 不退出）。如果某些场景需要 handoff（A 退出 B 接管），可以加一个 `handoff_to_agent` 工具。但 A2A 协议本身是 delegate 语义，handoff 需要额外设计。

---

## 2.7 事实声明

- 五原语、handoff、guardrails：OpenAI 官方博客 + 文档
- guardrails 不作用于 handoff：OpenAI 文档明确
- ~18k star

→ [下一章：AutoGen](03-AutoGen.md)
