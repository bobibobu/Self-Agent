# 第 3 章：AutoGen —— 群聊隐喻与维护模式教训

> 微软的多 Agent 对话框架，以 GroupChat 闻名。v0.4 彻底重写。
> **已转入维护模式**——这是本系列最重要的「教训案例」。

---

## 3.1 它是什么

地址 github.com/microsoft/autogen，~50-60k star（待核实）。但**微软已将其转入维护模式**，重心转向新的 *Microsoft Agent Framework*（~12.4k star）。

最早以 **GroupChat**（多 agent 围绕一个对话轮流发言）闻名。v0.4（2025 初）做了彻底重写。

---

## 3.2 v0.4 重构（2025 初）

### 三层架构

1. **autogen-core**：底层事件驱动运行时
2. **AgentChat**：高层多 Agent 对话 API
3. **扩展层**

### 从同步 GroupChat → 异步事件驱动

旧的 GroupChat 是**阻塞同步**的，扩展性差。v0.4 用**事件驱动 + 全异步**，支持分布式 agent。

还加了：内置 streaming、模块化可插拔。

---

## 3.3 ★ GroupChat：多 Agent 协作的「对话隐喻」

多个 agent 围绕一个**共享对话**轮流发言，像开会讨论。

### 群聊策略

- **Selector**：由一个 selector agent 决定下一个谁发言
- **RoundRobin**：轮流发言
- **Random**：随机
- 自定义

### 群聊的样子

```
[共享对话]
User: "设计一个推荐系统"
  ↓
PM Agent: "我建议先做需求分析..." 
  ↓
Architect Agent: "从架构角度，我建议..."
  ↓
Engineer Agent: "实现上，我建议..."
  ↓
...轮流发言直到收敛
```

### 对比 A2A（Self-Agent）

| 方面 | GroupChat（AutoGen） | A2A（Self-Agent） |
|---|---|---|
| 隐喻 | 开会讨论 | 派工单 |
| 协作方式 | 围绕共享对话轮流发言 | 一对一任务委派 |
| 适合 | 协作讨论、多视角 | 明确任务、解耦 |
| 共享 | 共享对话历史 | 不共享内部（不透明） |

GroupChat 偏「开会讨论」，A2A 偏「派工单」。前者适合需要多视角融合的任务，后者适合明确分工的任务。

---

## 3.4 ★ 教训：高 star 但已停更

AutoGen 50-60k star，但最终被放弃转向新框架。原因：**同步 GroupChat 的扩展性问题**。

### 问题根源

同步 GroupChat 是「一个对话，大家轮流」：
- agent 多了，对话历史膨胀
- 同步等待，慢
- 无法分布式扩展

v0.4 重写成事件驱动 + 异步，但**重写等于推倒重来**，最终微软选择另起炉灶（Microsoft Agent Framework）。

### 这是「多 Agent 编排该用消息总线还是图」的真实案例

AutoGen 的失败说明：**同步群聊扩展不动**。要么用事件驱动（AutoGen v0.4 / LlamaIndex），要么用图（LangGraph）。

### 选型启示

**警惕「高 star 但已停更」的项目。** AutoGen 50-60k star 也救不了它的架构债。选框架要看：
- 维护活跃度（commit 频率、issue 响应）
- 架构是否可持续
- 是否有明确路线图

Self-Agent 选 LangGraph（活跃维护、Pregel 架构可持续）规避了这个风险。

---

## 3.5 AutoGen 给我们的启示

1. **同步群聊扩展性差**：多 agent 编排要么事件驱动要么图，同步轮流走不通
2. **高 star ≠ 可持续**：选型要看架构和维护，不只看 star
3. **GroupChat 的「对话隐喻」有价值**：适合需要多视角融合的场景，但要注意扩展性
4. **重写的代价巨大**：架构选型要慎重，推倒重来成本极高

---

## 3.6 事实声明

- v0.4 重构：微软官方博客 autogen-v0-4
- 维护模式：属实，重心转向 Microsoft Agent Framework
- GroupChat 机制：AutoGen 文档
- star 50-60k 待核实

→ [下一章：CrewAI](04-CrewAI.md)
