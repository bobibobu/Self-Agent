# 第 4 章：CrewAI —— 角色化多 Agent

> **角色化（role-playing）多 Agent 框架**，灵感来自「人类组织里的协作方式」。
> 核心抽象 Crew / Agent / Task，直觉化、易上手。

---

## 4.1 它是什么

地址 github.com/crewaiinc/crewai，~34k star（待核实）。核心抽象：**Crew + Agent + Task** 三件套。

定位：让非技术利益相关方也能理解的多人协作——「这是研究员，那是作者」。

---

## 4.2 角色驱动

每个 Agent 有 role、goal、backstory，像剧本角色：

```python
researcher = Agent(
    role="资深研究员",
    goal="找到最权威的资料",
    backstory="你有 20 年研究经验，严谨细致",
    tools=[search_tool],
)
writer = Agent(
    role="技术作者",
    goal="把研究写成易懂的文章",
    backstory="你擅长把复杂技术讲清楚",
)
```

### 为什么角色化有用

- **直觉化**：非技术人能理解（「这是研究员，那是作者」）
- **目标明确**：每个 agent 有清晰 role/goal，减少跑偏
- **可复用**：角色定义可跨项目复用

---

## 4.3 Crew + Task + Agent 三件套

- **Crew**：容器，装一组 agent 和 task
- **Task**：工作单元，可指定 assigned_agent，也可让 crew 自动分配
- **Agent**：执行者（有 role/goal/backstory/tools）

```python
crew = Crew(
    agents=[researcher, writer],
    tasks=[
        Task(description="研究 LangGraph", assigned_agent=researcher),
        Task(description="写成文章", assigned_agent=writer),
    ],
    process=Process.sequential,
)
result = crew.kickoff()
```

---

## 4.4 Process 策略

- **sequential**：顺序执行（task1 → task2 → ...）
- **hierarchical**：有 manager agent 调度子 agent
- **consensual**：共识驱动

### ★ hierarchical process 本质是 orchestrator/router

hierarchical 模式下，有一个 **manager agent** 负责调度——它决定哪个子 agent 接哪个 task。

这本质上就是一个**内置的 orchestrator/router**（全书第 14 章的 Router 范式）。

**对比 Self-Agent**：Self-Agent 没有显式 router，但 `delegate_to_agent` + LLM 自主决策本质是「LLM 当 router」。CrewAI 的 hierarchical 把 router 显式化成一个 manager agent。

---

## 4.5 ★ 角色化 vs A2A（核心对比）

| 维度 | CrewAI（角色化） | A2A（Self-Agent） |
|---|---|---|
| 协作定义 | 剧本角色（role/goal/backstory） | 标准协议（Agent Card） |
| 直觉度 | **高**（非技术人能懂） | 中（要理解协议） |
| 标准化 | 低（CrewAI 自有抽象） | **高**（开放标准） |
| 跨框架 | 不能（绑 CrewAI） | 能（任意框架互通） |
| 适合 | 同框架内、需直觉表达 | 跨框架、需解耦 |

**CrewAI 直觉化、A2A 标准化**。两者不是替代，是不同场景的选择：
- 同框架内、要让非技术人理解协作 → CrewAI
- 跨框架、要长期解耦 → A2A

---

## 4.6 给 Self-Agent 的借鉴

### 借鉴①：hierarchical orchestrator 作为长任务升级方向

Self-Agent 的「已知限制」是「单层 ReAct，无子 Agent / 并行分解」。

CrewAI 的 hierarchical（manager agent 调度子 agent）是一种升级方向：
- 复杂任务由一个 planner agent 拆解
- 派给多个子 agent 并行/串行执行
- planner agent 汇总

这比单层 ReAct 更适合「重构整个模块」这类大任务。

### 借鉴②：角色化作为 Skill 的增强

Self-Agent 的 Skill 是「工具+提示词」打包。可以借鉴 CrewAI，给 Skill 加 role/goal/backstory 元数据，让 agent 扮演更明确的角色。

---

## 4.7 事实声明

- 三件套、process 策略：CrewAI 官方文档
- ~34k star 待核实

→ [下一章：Pydantic AI](05-Pydantic-AI.md)
