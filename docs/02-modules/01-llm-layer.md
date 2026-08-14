# LLM 多协议抽象层

> 这是 Self-Agent 的核心设计之一。本文档讲清楚：为什么自研、怎么抽象、三套协议差异、如何扩展。

---

## 一、设计目标

用**一套接口**同时支持三类主流大模型协议：

| Provider | 协议 | 接入方式 |
|---|---|---|
| **GLM（智谱）** | OpenAI 兼容 | `openai` SDK + 换 base_url |
| **OpenAI** | OpenAI 原生 | `openai` SDK |
| **Anthropic** | Anthropic 原生 | `anthropic` SDK |

上层 Agent 代码只依赖统一接口 `LLMClient`，**切换 provider 零改代码**。

---

## 二、为什么自研而不是用 LiteLLM？

[LiteLLM](https://docs.litellm.ai) 是流行的多 provider 统一库，能直接路由 `zai/glm-4.5-flash`。我们选择自研的考量：

| 维度 | LiteLLM | 自研抽象层 |
|---|---|---|
| 依赖体积 | 重（100+ provider 代码） | 轻（只引 openai + anthropic） |
| GLM 新功能支持 | 滞后（社区 PR） | 即时（自己加） |
| 工具调用格式控制 | 黑盒转换 | 完全透明可控 |
| 学习价值 | 调用现成 | 理解协议差异（面试加分） |
| 调试 | 难追踪 | 清晰可断点 |

**结论**：只接 3 个 provider 时，自研更轻、更可控、更适合学习。若未来要接 20+ provider 并做负载均衡，再引入 LiteLLM 的 Router。

---

## 三、核心接口设计

```python
# app/llm/base.py
@runtime_checkable
class LLMClient(Protocol):
    @property
    def provider_name(self) -> str: ...

    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    def stream_chat(self, request: ChatRequest) -> ChatStream: ...
    # ↑ 刻意不是 async def：它返回异步迭代器，本身就是普通方法
```

> `chat` 是 `async def`（等待完整响应），`stream_chat` 是**普通方法返回异步生成器**
> （`async for chunk in llm.stream_chat(req)`）——这是 Protocol 里少数签名不对称的地方。

用 `Protocol`（结构化子类型）而非抽象基类：provider 实现无需继承，**鸭子类型**即可，降低耦合。

### 统一数据模型（`app/llm/models.py`）

```
ChatRequest  ──→  ChatMessage[]  +  ToolDefinition[]  +  参数
                        │                  │
                        ▼                  ▼
              各 provider 把统一模型转成自己的格式
                        │
                        ▼
ChatResponse ◀── content + ToolCall[] + Usage
```

关键：`ChatMessage` 用统一的 `role` + `content` + `tool_calls` 表达，**与 provider 无关**。
每个 provider 实现负责互转。

---

## 四、三套协议的关键差异

这是面试高频考点。理解这些差异，就理解了为什么需要抽象层。

### 差异 1：system 消息的位置

```
OpenAI/GLM:  messages 数组里混着 {role: "system", ...}
Anthropic:   system 是顶层参数，不进 messages 数组
```

我们的处理（`providers/anthropic.py` 的 `_split_system`）：把 system 消息抽出来传给顶层 `system=` 参数。

### 差异 2：工具调用的消息格式

**OpenAI/GLM** —— 工具调用在 assistant 消息里：
```json
{"role":"assistant", "tool_calls":[{"id":"x","function":{"name":"f","arguments":"{}"}}]}
{"role":"tool", "tool_call_id":"x", "content":"结果"}
```

**Anthropic** —— 用 content blocks：
```json
{"role":"assistant", "content":[{"type":"tool_use","id":"x","name":"f","input":{}}]}
{"role":"user", "content":[{"type":"tool_result","tool_use_id":"x","content":"结果"}]}
```

注意 Anthropic 的工具结果放在 **user 角色** 里，且 arguments 是已解析的 dict 而非 JSON 字符串。

### 差异 3：usage 字段

```
OpenAI/GLM:  prompt_tokens / completion_tokens / total_tokens
Anthropic:   input_tokens / output_tokens  （无 total）
```

### 差异 4：流式事件结构

```
OpenAI/GLM:  chunk.choices[0].delta.content
Anthropic:   events 流（text_delta / message_stop 等），用 messages.stream() 的 text_stream
```

> 这些差异全部封装在各自的 provider 实现里，对 Agent 层完全透明。

---

## 五、GLM 接入详解（重点）

GLM（智谱 Z.AI）的 OpenAI 兼容端点：

```
国内: https://open.bigmodel.cn/api/paas/v4/
国际: https://api.z.ai/api/paas/v4/
```

接入只需 3 行：
```python
from openai import AsyncOpenAI
client = AsyncOpenAI(
    base_url="https://open.bigmodel.cn/api/paas/v4/",
    api_key=os.environ["GLM_API_KEY"],
)
# 之后与调 OpenAI 完全一样
```

### 模型选择建议（2026）

| 模型 | 适用场景 | 成本 |
|---|---|---|
| `glm-4.5-flash` | 开发调试、学习 | **免费** |
| `glm-4.6` / `glm-4.7` | 生产主力 | 付费 |
| `glm-5.2` | 旗舰、长上下文(1M) | 付费 |

本项目默认 `glm-4.5-flash`，零成本即可学习开发。

---

## 六、如何新增一个 Provider？

以接入 DeepSeek（同样 OpenAI 兼容）为例，**零新代码**：

1. 在 `.env` 加：
   ```ini
   DEEPSEEK_API_KEY=xxx
   DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
   DEEPSEEK_MODEL=deepseek-chat
   ```

2. 在 `config.py` 加对应字段

3. 在 `factory.py` 加一个分支：
   ```python
   if provider == "deepseek":
       return OpenAILikeClient(
           api_key=s.deepseek_api_key,
           base_url=s.deepseek_base_url,
           default_model=s.deepseek_model,
           provider_name="deepseek",
       )
   ```

完成。这就是抽象层的价值——**OpenAI 兼容的 provider 基本零成本接入**。

若是非 OpenAI 兼容协议（如自定义 HTTP），新建一个 provider 类实现 `LLMClient` 协议即可，上层代码不动。

---

## 七、文件清单

```
app/llm/
├── __init__.py          # 对外导出
├── base.py              # LLMClient Protocol（统一契约）
├── models.py            # ChatRequest/Response/Message 等统一模型
├── factory.py           # 按 config 路由到 provider
└── providers/
    ├── openai_like.py   # OpenAI 兼容（含 GLM、OpenAI、DeepSeek 等）
    └── anthropic.py     # Anthropic 原生协议
```
