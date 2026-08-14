# 性能优化实录（面试案例库）

> 本目录记录项目中真实发生的性能优化案例：怎么发现的、根因是什么、怎么修的、收益多少。
> 每个案例都按「发现 → 根因 → 方案 → 证据」组织，可直接用于面试叙述。

---

## 案例一：消灭双 LLM 调用——流式 tool_calls 的跨协议聚合

**一句话**：Agent 每一步推理都调了两次 LLM（流式出文本 + 非流式复查工具决策），延迟和 token 成本直接翻倍；通过在 provider 层聚合流式 tool_call 增量，收敛为单次调用。

### 1. 怎么发现的（Situation）

三个独立信号指向同一处：

1. **基准测试**：`scripts/benchmark.py` 对 `/chat` 链路做 mock-LLM 零延迟压测，p50 = 20ms。一个"零延迟 LLM"的请求框架开销不该这么高——链路里有重复工作。
2. **OpenTelemetry span**：给 LLM 调用加 span 后，肉眼可见**一个对话 turn 里出现两条 `chat` span**——这就是直接证据（`app/agent/nodes/agent_node.py` 的注释里写着这个判别法）。
3. **成本对账**：对话日志（Mongo）里记录的 usage 是流式那份的，但 provider 后台的调用次数是对账的两倍。

### 2. 根因（Task + 分析）

当时的实现是：

```
agent_node:
  ① stream_chat()  → 拿流式文本，逐 token 推给前端
  ② chat()         → 非流式"复查"一次，只为拿 tool_calls
```

为什么当初要复查？因为**三家协议的流式 tool_calls 都是跨 chunk 的增量**，当时没有做聚合，从流里拿不到完整的工具调用决策。

这带来三层伤害：

| 伤害 | 说明 |
|---|---|
| **成本翻倍** | 每步推理 2 次完整调用（prompt tokens 重复计费） |
| **延迟翻倍** | 真实 LLM 场景一次 1~3 秒，两次串行 2~6 秒 |
| **一致性缺陷** | 两次是独立采样！流式已把答案推给用户，复查却决定调工具 → 界面出现「答案 → 工具 → 第二个答案」的割裂体验 |

第三点最隐蔽——**温度 > 0 时两次采样的 tool_calls 决策可能不同**，这不是性能问题，是正确性问题。

### 3. 方案（Action）

核心思路：**把聚合责任下沉到 provider 层，让流式请求自己交出完整决策**。

**① 扩展 StreamChunk 契约**（`app/llm/models.py`）：

```python
class StreamChunk(BaseModel):
    content: str = ""                        # 增量文本，逐 chunk 透传
    tool_calls: list[ToolCall] | None = None # ★ 聚合完成的结果，仅流末尾 chunk 携带
    usage: Usage | None = None               # ★ 同上
    finish_reason: str | None = None
    model: str = ""                          # ★ 同上
```

约定：文本走增量 chunk；**tool_calls / usage / model 在流结束时一次性交出**。消费端一次流式请求拿到全部信息。

**② OpenAI 协议：按 index 聚合增量**（`providers/openai_like.py`）

OpenAI 兼容协议（GLM 同）的流式 tool_calls 是这样到达的：

```
chunk1: tool_calls[0] = {index:0, id:"call_x", function:{name:"get_weather", arguments:'{"ci'}}
chunk2: tool_calls[0] = {index:0,                          arguments:'ty":"北京"}'}
```

每个增量带 `index`，`id`/`name` 只在首个 chunk 出现，`arguments` 是**分片字符串**。聚合器按 index 归并、拼接 arguments、最后 `json.loads`：

```python
acc: dict[int, dict] = {}          # index → {id, name, args_buf}
...
slot["args"] += fn.arguments       # 拼接分片
...
# 流结束：收尾 chunk 一次性交出
yield StreamChunk(tool_calls=..., usage=..., model=...)
```

防御细节：
- 个别兼容端点不给 `index` → 退化为 0
- arguments JSON 不完整（模型被截断）→ **不静默丢弃**，包成 `{"_raw": ...}` 交上层报错
- `stream_options={"include_usage": True}` 让流尾带 usage

**③ Anthropic 协议：复用 SDK 的本地组装**（`providers/anthropic.py`）

Anthropic 的工具入参走 `content_block_delta` 的 `input_json_delta`（partial JSON）。但 SDK 的 `messages.stream()` 上下文管理器提供 `get_final_message()`——它**在本地把事件流组装成完整消息，不产生额外 API 调用**。所以直接：

```python
async with client.messages.stream(...) as stream:
    async for text in stream.text_stream:   # 文本增量照常透传
        yield StreamChunk(content=text)
    final = await stream.get_final_message() # 本地组装，0 网络开销
yield StreamChunk(tool_calls=parse(final)...) # 收尾 chunk 交出聚合结果
```

> 旧代码其实也调了 `get_final_message()` 但只取了 `stop_reason`，把 tool_use 块丢了——所以才需要上层复查。这是个"API 会用但没用对"的典型案例。

**④ agent_node 收敛为单次消费**：

```python
async for chunk in llm.stream_chat(request):
    if chunk.content:  → writer 推 token（真·流式）
    if chunk.tool_calls: → 收下聚合结果
    if chunk.usage: → 收下用量
# 循环结束即同时持有 文本 + 工具决策 + usage，直接构造 AIMessage
```

### 4. 证据（Result）

**调用次数断言**（`scripts/verify_stream.py`，可复跑）：

```
• 单次调用验证：2 个 agent 步骤 = 2 次 LLM 调用（无复查冗余）
```

一轮「查天气」对话含 2 个 agent 步骤（决策调工具 → 工具后总结），优化前是 **4 次**调用（每步 2 次），优化后 **2 次**——恰好每步 1 次。脚本里 `assert mock_llm._call_count == 2`，退化成双调用会直接断言失败。

**框架基准**（`scripts/benchmark.py`，单 worker / mock LLM）：

| 场景 | 吞吐 | p50 延迟 |
|---|---|---|
| `/chat` 完整链路（并发 8） | ~300 rps | 20ms |
| `/chat`（模拟 LLM 500ms，并发 50） | ~80 rps | 556ms |

框架开销 55ms 级；真实场景下省掉的那一次调用 = **端到端延迟和 token 成本直接减半**（原串行两次 LLM 变一次）。

> 面试诚实原则：框架层基准跑的是优化后代码，"优化前"的量化我用**结构性论证**（每步 2 次调用 → 1 次）+ 调用次数断言证明，不编造 before/after 基准对比。编数据被追问就穿帮，真实数据 + 诚实方法论反而加分。

### 5. 面试话术（60 秒版）

> 我们的 Agent 有个性能问题：每步推理调了**两次** LLM——流式出文本、非流式复查工具决策。发现它不是靠读代码，是三个信号：基准测试里 mock-LLM 零延迟下 p50 仍有 20ms；加了 OpenTelemetry span 后一个 turn 里出现两条 chat span；provider 账单对不上日志。
>
> 根因是三家协议的流式 tool_calls 都是跨 chunk 增量，当时没做聚合。修法是把聚合下沉到 provider 层：OpenAI 协议按 index 归并、拼接 arguments 分片；Anthropic 复用 SDK 的 get_final_message 本地组装，零额外网络调用。StreamChunk 契约改成"末尾 chunk 一次性交出 tool_calls 和 usage"，agent 节点单次消费。
>
> 收益不只是延迟成本减半——原来两次独立采样在温度大于零时**工具决策可能不一致**，界面上会出现"答案→工具→第二个答案"，这是正确性问题，一并修掉了。验证用调用次数断言锁死：2 步对话恰好 2 次调用，退化会直接测试失败。

### 6. 追问链预演

**Q：为什么不直接用 LangChain 的 `ChatModel.astream()`，它不是自带 tool_call 聚合吗？**
A: 因为整个项目用的是自研多协议 LLM 抽象层（为了统一 GLM/OpenAI/Anthropic 三套协议、掌控格式转换），不引入 LangChain ChatModel。代价就是流式聚合要自己做——这正是自研抽象层的边界成本，我认这个账。

**Q：聚合器怎么处理流中断/参数 JSON 不完整？**
A: 三层防御：解析失败的 arguments 不静默丢弃，包成 `{"_raw": 原文}` 交给上层工具节点报错；不给 index 的兼容端点退化为 0 号槽位；agent 层保留"流既无文本也无工具调用时回退一次非流式"的兜底（正常 provider 路径不触发）。

**Q：这个优化对 P99 有什么影响？**
A: 对话型请求的延迟分布 = k × 单次 LLM 延迟（k 为 agent 步数 × 原来的 2）。每步少一次调用，意味着 P99 大约**减半**——因为 LLM 延迟是对数正态分布的长尾，少一次采样就少一次踩长尾的机会。

**Q：怎么保证以后不退化回双调用？**
A: 两道锁：① `verify_stream.py` 的调用次数断言（2 步 = 2 次，多了直接 fail）；② OTel span 里一个 turn 出现两条 chat span 就是退化信号，可在告警里配。

---

## 关联优化（同一次改造里顺手做的，面试可作补充弹药）

### A. 时间戳放消息末尾，保护 KV 缓存前缀

系统提示词里的「当前时间」每轮都变。如果拼在 SYSTEM_PROMPT（消息列表头部），**provider 侧的 prompt 缓存前缀每轮全失效**，缓存命中归零。修法：时间戳改为独立的 HumanMessage 拼在**对话末尾**，只进"发给 LLM 的这一份"，不写回持久化 state。

### B. 系统提示走 config 不写回 state

原来每轮把系统提示 append 进 state 的 messages → 第 N 轮的 prompt 里有 N 份系统提示，token 线性膨胀。修法：系统提示通过 `config["configurable"]["system_prompt"]` 传入，agent_node 拼进"发给 LLM 的这一份"，持久化历史保持干净。

### C. 用 span 树观测退化

`app/core/telemetry.py` 给 agent.turn / llm.chat 建了 span 树（OpenTelemetry 兼容命名：`gen_ai.*`）。性能问题从"猜"变成"看"——这也是案例一能被快速定位的前提。

---

## 案例二：三次缓存 miss 的连锁修复——工具 Schema / 摘要 / 提示词文件

**一句话**：cProfile 显示 /chat 热路径近两成 CPU 花在每次请求重新生成 14 个工具的 Pydantic JSON Schema 上；顺着"静态数据为何每请求重算"这个思路排查，又揪出两处同类问题（长会话每轮多一次摘要 LLM 调用、每请求一次提示词文件同步读），三处缓存修复后框架吞吐 +27%。

### 1. 怎么发现的（Situation）

`scripts/benchmark.py` 压出一个反直觉现象：**并发越高吞吐越低**（并发8 → 374 rps，并发64 → 234 rps）。mock LLM 零延迟下这不该发生——说明热路径有 CPU 密集串行段。用 cProfile 对 /chat 做 200 次请求采样，`tottime` 榜首三行：

1. `bridge.build_tool_definitions` 里 600 次 `model_json_schema`（约 18% CPU）——工具注册表明明是启动时固定的，每次 LLM 调用却在重算 14 份 Schema；
2. `context_manager.compress_if_needed` 每次都触发"上下文压缩"日志——翻代码发现模块文档写着"摘要缓存（同一段历史不重复摘要）"，**但实现里根本没有缓存**：长会话每轮、ReAct 循环每次回到 agent 节点，都要多调一次 LLM 全量重摘；
3. `prompt_store.get_current_prompt` 每请求一次同步 `read_text` + `json.loads`——Hermes 优化提示词的频率是"每天几次"，却在为每个请求付磁盘 IO。

### 2. 根因（Task + 分析）

三处是同一个反模式：**把低频变化的静态数据当成了每请求数据**。

- 工具 Schema：`build_chat_request` 每次都 `build_tool_definitions(tools)`，对每个工具做 `args_schema.model_json_schema()`。Pydantic 的 schema 生成是全量反射遍历，纯 CPU，且结果确定。
- 摘要：超 20 条消息后，`dialog[:cut]` 每轮多 1~2 条 → 每轮都是"新前缀" → 每轮全量重摘。真实 LLM 下一轮对话 = 1 次主调用 + 1~2 次摘要调用，延迟和 token 双输。
- 提示词文件：`get_current_prompt()` 无条件读盘。

### 3. 方案（Action）

**A. 工具 Schema 缓存**（`app/agent/nodes/bridge.py`）：模块级 dict，key = `(name, description, args_schema)`。这里踩了个**很值得讲的坑**：第一版 key 写的是 `type(args_schema)`——测试立刻打脸，因为**所有 Pydantic 模型的元类都是同一个 `ModelMetaclass`**，`type()` 对任何 schema 类返回同一个对象，缓存永远命中，MCP 工具换了 Schema 也不会失效。修正：key 直接放 schema 类本身（类可哈希），且只对 `isinstance(args_schema, type)` 的标准用法缓存。这个 bug 是"为优化写测试"的直接回报——不上线就发现，而不是等 MCP 工具更新后静默发错 Schema。

**B. 摘要缓存 + 迟滞窗口**（`app/agent/context_manager.py`）：按 thread 缓存 `{pos, id, summary}`（pos = 已摘要到的下标，id = 边界消息 id 用于校验历史确实是对话的追加式延伸）：

- 新积累的早期消息 < 6 条 → 直接复用旧摘要（近期消息暂时多留几条，上限 keep_recent+6）；
- ≥ 6 条 → 一次**增量摘要**（旧摘要 + 新消息喂给 LLM，输出合并版），比全量重摘省 token 也更快；
- 边界消息 id 对不上（会话被重置）→ 缓存作废，全量重摘。

效果：摘要 LLM 调用从"每轮 1+ 次"降到"每 6 条新消息 1 次"，ReAct 循环内的重复调用完全消除。ToolMessage 边界安全（recent 不能以 ToolMessage 开头）在缓存复用路径上同样保证。

**C. 提示词 mtime 缓存**（`app/evolution/prompt_store.py`）：`(st_mtime_ns, st_size)` 没变就直接返回缓存内容；`save_version` 写文件后 mtime 变化自动失效。

### 4. 证据（Result）

mock LLM 0ms、单事件循环、内存 checkpointer，同口径（共用 thread_id 长会话 ×100 并发8）：

| 指标 | 优化前 | 优化后 |
|---|---|---|
| 吞吐 | 373.7 rps | 474.8 rps（**+27%**） |
| p50 | 20.0 ms | 13.5 ms（**-33%**） |
| p95 | 25.0 ms | 20.7 ms |

新会话稳态（每请求独立 thread）：680 rps / p50 10.7ms；流式路径 334 → ~400-500 rps。
回归测试：`tests/test_perf_optimizations.py` 11 个用例锁住三处缓存行为（含元类坑、缓存失效、增量触发、ToolMessage 边界安全）。

### 5. 面试一句话

"压测发现吞吐随并发上升而下降，profile 定位到三处'静态数据每请求重算'的反模式；修的时候还差点引入一个 Pydantic 元类导致的缓存永不失效 bug，被自己写的测试当场拦下——所以我特别信'优化必须配回归测试'这条规矩。"

---

## 案例三：TTFT 是假的——进程内基准测不出流式性能

**一句话**：用 httpx `ASGITransport` 进程内压测流式端点，测出 TTFT ≈ 总耗时（4.6s）；排查后发现是 transport 把整个响应体缓冲完才交付——token 其实一直在流，是测量工具在"攒着"。改走真实 TCP 后 TTFT 1.8s、token 间隔 27ms。

### 1. 怎么发现的（Situation）

给 Agent 补 QPS 基准时顺手测了流式 TTFT：进程内（ASGITransport）测出所有 token "同时到达"（TTFT=5763ms，总耗时=5764ms，70 个 token 零间隔）。第一反应是"流式实现有 bug，被什么东西缓冲了"——顺着这条错误假设查了 SSE 编码、LangGraph astream 的 custom 模式、provider 的 stream_chat，全都没问题。

### 2. 根因（Task + 分析）

**测量工具才是元凶**：httpx 的 ASGITransport 是"进程内模拟服务器"实现，它把 ASGI 应用的响应体**完整收集后**才作为响应返回——不支持真流式交付。生产链路上的 uvicorn + TCP + httpx 是逐 chunk 透传的，所以进程内基准天然测不了 TTFT/token 间隔这类"时间分布"指标。

这类陷阱的通用形态：**被测系统和测量仪器共享同一个抽象层时，仪器会继承这层的伪影**。mock LLM 是有意共享（隔离变量），transport 缓冲是无意识共享（污染变量）——两者都让数字偏离真实，但只有后者是错的。

### 3. 方案（Action）

基准分两层，各测各的：
- **框架层**（mock LLM 0ms + ASGITransport）：测吞吐和 CPU 热点——延迟形态不重要，buffering 无害；
- **真实层**（真 uvicorn + TCP + 真实 GLM）：测 TTFT、token 间隔、真实 rps——传输层必须和生产同构。

结论记录在 `docs/04-guides/性能基准报告.md` §3，benchmark 脚本注释里也写了这个坑。

### 4. 证据（Result）

| 指标 | ASGITransport（进程内） | 真实 TCP |
|---|---|---|
| TTFT | ≈ 总耗时（假） | 1.8~2.8s（真） |
| token 间隔 | 0ms（假） | ~27ms（≈37 token/s） |
| 结论 | 只能测吞吐 | 才能测流式体验 |

### 5. 面试一句话

"我测流式 TTFT 时发现所有 token 同时到达，追了一圈自己的流式实现没问题，最后发现是 httpx 进程内 transport 在缓冲响应体——测量仪器和被测系统共享抽象层时会继承伪影。所以我的基准分两层：进程内 mock 测框架吞吐，真实 TCP 测流式体验。"

---

## 案例素材使用建议

| 场景 | 建议讲法 |
|---|---|
| 被问"性能优化经历" | 案例一完整讲（发现三板斧 → 根因三层 → 方案四步 → 证据断言） |
| 被问"LLM 成本控制" | 双调用消灭 + KV 缓存前缀保护 + 模型分级（flash/旗舰路由） |
| 被问"怎么调试难复现问题" | span 观测法：一个 turn 两条 chat span 的判别式 |
| 被问"测试怎么锁住优化成果" | 调用次数断言 + 契约测试（StreamChunk 末尾 chunk 约定） |
| 被问"踩过最深的坑" | BaseHTTPMiddleware 缓冲流式响应（见 README Q28 关联），或本案例的"两次采样不一致" |
| 被问"怎么测性能/指标可信吗" | 案例三完整讲（假 TTFT → 仪器伪影 → 两层基准法） |
