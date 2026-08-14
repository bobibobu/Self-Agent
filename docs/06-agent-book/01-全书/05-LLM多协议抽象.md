# 第 5 章：LLM 多协议抽象

> 目标：读完这章，你能讲清楚「为什么要有 LLM 抽象层」「三家协议差在哪」「怎么加一家新的」。

---

## 5.1 问题：三家 API 长得不一样

本项目支持三家大模型：**智谱 GLM、OpenAI、Anthropic**。但它们的 API **长得不一样**：

| 差异点 | OpenAI / GLM | Anthropic |
|---|---|---|
| 系统消息 | 混在 `messages` 数组里（role: "system"） | 顶层 `system=` 参数，**不进 messages** |
| 工具调用 | assistant 消息带 `tool_calls`；结果用 `role:"tool"` | 用 content blocks（`tool_use`/`tool_result`）；**结果放 user 角色里**；arguments 是已解析 dict |
| usage 字段 | `prompt_tokens` / `completion_tokens` / `total_tokens` | `input_tokens` / `output_tokens`（无 total） |
| 流式事件 | `chunk.choices[0].delta.content` | events 流（`text_delta` / `message_stop` 等） |

如果上层 Agent 代码直接对接这三家，会写满 `if provider == "openai"` 这种分支，混乱且难维护。

**LLM 抽象层**就是来解决这个的：定义一套**统一的接口和数据模型**，三家 provider 各自实现「统一模型 ↔ 自家格式」的转换。上层只依赖统一接口，换 provider 改配置即可。

---

## 5.2 统一接口：LLMClient 协议

`app/llm/base.py` 用 Python 的 `Protocol`（鸭子类型）定义契约：

```python
@runtime_checkable
class LLMClient(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def default_model(self) -> str: ...

    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    def stream_chat(self, request: ChatRequest) -> ChatStream: ...
```

注意 `stream_chat` **不是 `async def`**——因为各 provider 的实现都是**异步生成器**（`async def` + `yield`），调用后直接返回 AsyncIterator。如果写成 `async def ... -> ChatStream`，类型检查会认为要先 await 一次，和 `async for chunk in llm.stream_chat(req)` 的真实用法对不上。

---

## 5.3 统一数据模型

`app/llm/models.py` 定义所有 provider 无关的类型：

```python
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None     # assistant 携带
    tool_call_id: str | None = None              # tool 携带（配对用）
    name: str | None = None

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    model: str | None = None
    temperature: float = 0.7
    tools: list[ToolDefinition] | None = None
    tool_choice: str = "auto"

class StreamChunk(BaseModel):
    content: str = ""                            # 增量文本
    tool_calls: list[ToolCall] | None = None     # 仅末尾 chunk
    usage: Usage | None = None                   # 仅末尾 chunk
```

**所有 provider 的实现负责把自家原生格式 ↔ 这套模型互转。** 这是「适配器模式」。

---

## 5.4 工厂路由

`app/llm/factory.py` 按配置创建对应 client：

```python
def create_llm_client(provider: ProviderName) -> LLMClient:
    s = get_settings()
    if provider == "glm":
        return OpenAILikeClient(api_key=s.glm_api_key, base_url=s.glm_base_url,
                                default_model=s.glm_model, provider_name="glm", ...)
    if provider == "openai":
        return OpenAILikeClient(api_key=s.openai_api_key, ...)
    if provider == "anthropic":
        return AnthropicClient(api_key=s.anthropic_api_key, ...)
```

**关键设计**：GLM 和 OpenAI **共用同一个 `OpenAILikeClient`**——因为 GLM 暴露了完全 OpenAI 兼容的 `/chat/completions` 端点，只换 `base_url`。这叫「零适配接入」。

GLM 接入只需配置：
- `GLM_API_KEY`：智谱的 key（有免费额度）
- `GLM_BASE_URL`：`https://open.bigmodel.cn/api/paas/v4/`
- `GLM_MODEL`：`glm-4.5-flash`（免费）/ `glm-4.6` / `glm-5.2` 等

---

## 5.5 桥接层：两个世界的翻译

这里有个微妙之处：**LangGraph 的 State 用的是 LangChain 的消息类**（HumanMessage / AIMessage / ToolMessage），但本项目的 LLM 层用的是统一的 ChatMessage。

`app/agent/nodes/bridge.py` 就是这两个世界的翻译层：

```python
def lc_to_chat_messages(messages: list[BaseMessage]) -> list[ChatMessage]:
    """LangChain 消息 → 统一 ChatMessage。"""
    # SystemMessage → role:"system"
    # HumanMessage → role:"user"
    # AIMessage → role:"assistant"（带 tool_calls）
    # ToolMessage → role:"tool"（带 tool_call_id）
```

为什么会有两套？因为 LangGraph 强制用 LangChain 消息类（State 类型是 `Annotated[list[AnyMessage], ...]`），而本项目不想让 LLM 层耦合 LangChain。bridge.py 把这两个解耦的世界接起来。

---

## 5.6 ★ 流式工具调用的拼装（最绕的实现细节）

这是整个 LLM 层最绕的部分，但理解了就知道「真·token 流式」是怎么做到的。

### 问题

OpenAI 兼容协议里，**工具调用是跨多个 chunk 的增量**：

```
chunk1: tool_calls[0] = {index:0, id:"call_x", function:{name:"f", arguments:"{\"a\""}}
chunk2: tool_calls[0] = {index:0, function:{arguments:":1}"}}
chunk3: (结束)
```

每个 chunk 只给 arguments 的一小段字符串。为什么？因为 LLM 是逐 token 生成的，`{"a":1}` 这个 JSON 也是逐字符吐的。服务端把这些增量按 `index` 分流，让客户端自己拼。

### 解决

`app/llm/providers/openai_like.py:170` 的 `stream_chat` 内部按 index 聚合：

```python
acc: dict[int, dict[str, Any]] = {}  # index → {id, name, args_buf}
async for chunk in stream:
    for tc in (delta.tool_calls or []):
        idx = tc.index if tc.index is not None else 0
        slot = acc.setdefault(idx, {"id": "", "name": "", "args": ""})
        if tc.id:
            slot["id"] = tc.id
        if fn.name:
            slot["name"] = fn.name
        if fn.arguments:
            slot["args"] += fn.arguments  # 拼字符串
```

聚合好的完整 tool_call 在**流末尾一次性给出**（`StreamChunk.tool_calls`）。

### 为什么这么设计

这样调用方**一次流式调用就能同时拿到**：
- 逐 token 的文本（实时推给前端）
- 完整的工具调用决策（不用再补一次非流式调用）

**曾经的错误实现**：先 stream 出文本，再 chat() 复查 tool_calls。两次独立采样，成本翻倍，而且两次结果可能不一致——流式已经把答案推给用户了，复查却决定调工具，界面上就会出现「答案 → 工具 → 第二个答案」的混乱。trace 里一个 turn 下若出现两条 chat span，就是这种退化。

---

## 5.7 为什么自研而不用 LiteLLM

LiteLLM 是一个统一 100+ provider 的库。本项目只接 3 家，自研了。权衡：

| 维度 | LiteLLM | 自研 |
|---|---|---|
| 依赖体积 | 重（100+ provider 全打包） | 轻（只引 openai + anthropic SDK） |
| GLM 新功能支持 | 滞后（等社区 PR） | 即时（自己加） |
| 工具调用格式控制 | 黑盒转换 | 完全透明可控 |
| 学习价值 | 调现成 | 理解协议差异 |
| 调试 | 难追踪 | 清晰可断点 |

**结论**：只接 3 家时自研更轻更可控。若未来要接 20+ provider 并做负载均衡，再引入 LiteLLM 的 Router。

---

## 5.8 为什么用 Protocol 而非抽象基类

`LLMClient` 用 `typing.Protocol`（结构化子类型/鸭子类型），不是 `ABC`。

区别：
- `ABC`：provider 实现类必须**显式继承** `LLMClient`，引入耦合
- `Protocol`：provider 实现只要**长得像**（有这几个方法）就算实现，无需继承

这是「依赖倒置」的体现：上层依赖契约，provider 实现不依赖上层框架。换 provider 零代码改 Agent。

---

## 5.9 怎么加一家新的 provider

### 情况 A：它是 OpenAI 兼容的（最常见）

DeepSeek、Moonshot、Together、Anyscale 等都是。**零代码改 Agent**，只需：

1. `app/core/config.py` 加配置项（api_key / base_url / model）
2. `factory.py` 加一个分支，复用 `OpenAILikeClient`

### 情况 B：它有自己的协议（如 Anthropic）

1. 新建 `app/llm/providers/xxx.py`，实现 `LLMClient` 协议
2. 在里面写「统一模型 ↔ 自家格式」的转换
3. `factory.py` 加分支

Anthropic 的实现就是个完整范例：system 消息要拆出来放顶层参数、工具结果要放 user 角色、usage 字段名不同……这些差异全封装在 `providers/anthropic.py` 里，对 Agent 透明。

---

## 5.10 外部世界怎么做

| 项目 | LLM 抽象 |
|---|---|
| **LangChain** | ChatModel 体系（ChatOpenAI/ChatAnthropic），强制要求 create_react_agent |
| **LiteLLM** | 统一 100+ provider，适合规模化集成 |
| **OpenAI Agents SDK** | provider-agnostic（也支持其他模型）但偏 OpenAI |
| **Pydantic AI** | 强类型，工具参数/返回都用 Pydantic 校验 |
| **Cline** | model-agnostic（Claude/GPT/Gemini/Ollama 都行） |
| **Self-Agent**（本项目） | 自研轻抽象，3 家够用、可控 |

**趋势**：MCP 让工具层 provider-agnostic，各家在 LLM 层也逐渐收敛到「OpenAI 兼容 + 个别原生」的两层模式。

---

## 5.11 面试一句话

> **Q：为什么自研 LLM 抽象而不用 LangChain 的 ChatModel？**
> A：LangChain ChatModel 耦合了它的消息类型和工具调用协议，且 create_react_agent 强制要求 LangChain 模型。自研让我们完全掌控消息格式转换、解耦 LangGraph 与具体 SDK、统一流式和 token 统计。

> **Q：GLM 怎么接入的？**
> A：智谱暴露了 OpenAI 兼容的 /chat/completions 端点，只需换 base_url，复用 openai SDK。零适配，工具调用、流式、token 统计全白嫖。

下一章：工具系统——Agent 的手。

→ [第 6 章：工具系统](06-工具系统.md)
