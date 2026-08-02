# 第 5 章：Pydantic AI —— 类型安全优先

> **类型安全（type-safe）优先**的 Python Agent 框架，Pydantic 团队出品。
> 「类型即契约」哲学——工具参数、返回值、Agent 输出都用 Pydantic 校验。

---

## 5.1 它是什么

地址 github.com/pydantic/pydantic-ai，~18k star。Pydantic 团队出品。

定位：**类型安全贯穿全流程**。和 mypy/pyright 深度集成，工具参数、返回值都用 Pydantic model 校验。

---

## 5.2 核心设计

### ① 类型安全贯穿全流程

工具参数、返回值、Agent 输出都用 Pydantic model：

```python
from pydantic import BaseModel
from pydantic_ai import Agent

class ResearchResult(BaseModel):
    topic: str
    sources: list[str]
    confidence: float

research_agent = Agent(
    model="claude-3-5-sonnet",
    result_type=ResearchResult,  # ← 输出强制校验成强类型
)

@research_agent.tool
async def search(ctx, query: str) -> list[str]:  # ← 参数类型校验
    ...
```

LLM 输出**直接验证成强类型对象**，不是裸字符串。

### ② 结构化输出

`result_type=ResearchResult` 让 agent 的输出被强制校验成 `ResearchResult`。LLM 输出格式不对会报错，不会静默传下去。

### ③ 依赖注入

内建 DI（dependency injection）系统，工具的依赖（数据库连接、配置）通过 DI 注入，便于测试。

### ④ 是 Pydantic AI 工程栈的一部分

- **Logfire**：可观测
- **Evals**：评测
- **Pydantic AI**：构建

三者配套，形成完整的「构建-观测-评测」工程栈。

---

## 5.3 ★ 「类型即契约」哲学

Pydantic AI 的核心信仰：**类型就是契约**。

- 工具参数是契约：`query: str` 保证拿到的是字符串
- Agent 输出是契约：`result_type=ResearchResult` 保证输出结构
- 返回值是契约：类型注解就是文档

这让整个 agent 系统像写普通 Python 一样**可静态检查、可类型推导、IDE 友好**。

### 对比 Self-Agent

Self-Agent 用 Pydantic 做配置（`Settings(BaseSettings)`）和 LLM 模型（`ChatMessage(BaseModel)`），但：
- 工具参数靠 `@tool` + 类型注解（LangChain 自动转 schema），有类型但没强制校验
- Agent 输出是裸 `AIMessage.content`（字符串），没有结构化契约

**借鉴价值**：如果 Self-Agent 要做「输出结构化」（比如让 agent 输出 JSON 决策），Pydantic AI 的 `result_type` 模式值得学。

---

## 5.4 给 Self-Agent 的借鉴

### 借鉴①：Agent 输出结构化契约

Self-Agent 的 agent 输出是裸文本。某些场景（如 A2A 委托、工具决策）需要结构化输出。可以借鉴 Pydantic AI 的 `result_type`，让特定 agent 的输出强制校验成 Pydantic model。

### 借鉴②：工具参数严格校验

Self-Agent 的工具参数靠 LangChain 的 schema 生成，运行时不强制校验。可以加一道 Pydantic 校验，防止模型给出格式错误的参数。

### 借鉴③：配套评测（Evals）

Pydantic AI 配套 Evals 做评测。Self-Agent 当前有测试但没有「agent 行为评测」（如回答质量打分）。这是值得补的能力。

---

## 5.5 事实声明

- 类型安全、result_type、DI、工程栈：Pydantic AI 官方文档
- ~18k star

→ [下一章：LlamaIndex Workflows](06-LlamaIndex.md)
