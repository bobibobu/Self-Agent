# 面试官拷问与解答

> 模拟高级面试官针对 Self-Agent 项目的深度提问，附详尽参考答案。
> 每个答案结合项目实际实现，可对照源码。

> 📈 **性能/优化实战经历**（面试高频加分项）：见
> [optimization-cases.md](optimization-cases.md) —— 真实案例库，含
> 「消灭双 LLM 调用」（发现→根因→方案→量化证据→追问链预演）。

---

## 一、架构设计类

### Q1: 讲讲你这个 Agent 的整体架构，为什么这么分层？

**答**：分五层，每层只依赖正下方：
- **API 层**（FastAPI）：接收请求，不关心 Agent 实现
- **Agent 编排层**（LangGraph）：状态图驱动 ReAct 循环，不关心用哪个 LLM
- **LLM 抽象层**：统一 GLM/OpenAI/Anthropic 协议，只暴露 `LLMClient` 接口
- **记忆层**：短期(checkpointer)+长期(store)+画像(Neo4j)+日志(Mongo)
- **数据层**：4 库异步连接管理

这样分层的好处是**依赖方向单一**：换任何一层不影响其他。比如把 GLM 换成 OpenAI，Agent 代码一行不改——因为 Agent 只依赖 `LLMClient` 协议，不感知具体 provider。

### Q2: 如果 QPS 上万，瓶颈在哪？怎么扩展？

**答**（以下有实测数据支撑，完整报告见 [性能基准报告](../04-guides/性能基准报告.md)，2026-08 实测）：
0. **先分层定位瓶颈**：mock LLM 零延迟压测框架层——单 worker 新会话 ~680 rps、长会话 ~475 rps、流式 ~400-500 rps；接真实 GLM 后并发 10 只有 **2.5 rps**（e2e p50 ≈ 2.6s）。**框架开销占不到 1%，真实瓶颈在 LLM provider**——此时扩应用实例无收益，先解决 provider 侧。
1. **LLM 调用是最大瓶颈**（秒级延迟）。横向扩展应用层无状态实例 + 对 LLM 做**请求队列与并发控制**（避免触发 provider 限流）、必要时上多 key 池。本项目用 Redis 做缓存（相同问题命中）和限流计数。
2. **Postgres 连接池**：业务表与 LangGraph checkpointer/store 共用一个 psycopg 3 `AsyncConnectionPool`（`POSTGRES_POOL_MAX_SIZE` 可调，已设 `prepare_threshold=0` 可直接挂 PgBouncer 事务池）。2026-10 之前业务表另开一个 asyncpg 池，一个进程两套驱动、两倍连接数，已合并。
3. **短期记忆**：高并发下 Postgres checkpointer 会成热点，可换 ShardedPostgresSaver 按 thread_id 分片。
4. **无状态化**：把会话状态全放外部存储（已做到——checkpointer 在 DB），应用实例可随意水平扩缩。

### Q3: 为什么 LLM 用自研抽象层，不用 LangChain 的 ChatModel 或 LiteLLM？

**答**：
- **不用 ChatModel**：`create_react_agent` 强制要求 LangChain 模型，会耦合 LangChain 的消息类型和工具协议，失去对格式转换的掌控。
- **不用 LiteLLM**：只接 3 个 provider 时，LiteLLM（100+ provider 代码）过重；且 GLM 新功能支持滞后；工具调用转换是黑盒难调试。
- **自研**：用 `Protocol`（鸭子类型）定义统一接口，每个 provider 自己做格式互转，完全透明可控。代价是失去 LangSmith 自动追踪，用结构化日志 + trace_id 补偿。

### Q4: 你的 Agent 是 ReAct 模式，和 Plan-and-Execute、多 Agent 各有什么取舍？

**答**：
- **ReAct**（本项目）：每步思考→行动→观察，灵活但可能多轮。适合工具不确定、需根据中间结果调整的场景。
- **Plan-and-Execute**：先规划完整步骤再执行，减少 LLM 调用但计划可能僵化。
- **多 Agent**（Phase 4 的 A2A）：分工协作，适合复杂任务，但协调开销大。
本项目用 ReAct 是因为通用助理场景工具调用路径不可预测；复杂任务可通过 A2A delegate 给专业 Agent。

---

## 二、并发与异步类

### Q5: 为什么全程用 async？同步 LLM 调用会怎样？

**答**：用 `AsyncOpenAI` / `AsyncAnthropic` / psycopg 3 异步池 / PyMongo 原生 async（`AsyncMongoClient`，替代已 EOL 的 motor）/ redis.asyncio，避免阻塞事件循环。若在 async 节点里用同步 `openai.OpenAI`，会**阻塞整个事件循环**——所有并发请求被串行化，吞吐量大幅下降（实测 3x 以上差异）。LangGraph 的 async 图（`astream`/`ainvoke`）配合 async client，能让节点内的 IO 真正并发。

### Q6: 多个工具调用怎么并发执行？

**答**：`tools_node` 用 `asyncio.gather` **并发执行**同一轮的所有 tool_calls（`tools_node.py:190`）：
```python
results = await asyncio.gather(*[_run_one(c) for c in tool_calls])
```
当一轮有多个独立工具调用（如同时查天气+算时间）时，并发能把总耗时从"求和"降到"取最大"。
每个 call 走独立的 `_run_one` 流水线（策略检查 → 审批 → 执行），单个工具失败不影响其他结果返回。
（历史：早期是顺序执行为简化错误处理，后来才改并发——若被追问"为什么当时顺序"，答"先保正确再保快"。）

### Q7: 你说用 Redis 做限流，具体怎么做？

**答**：滑动窗口或令牌桶。用 Redis 的 INCR + EXPIRE 实现固定窗口计数：
```python
key = f"rate:{user_id}:{minute}"
count = await redis.incr(key)
if count == 1:
    await redis.expire(key, 60)
if count > LIMIT:
    raise RateLimitError()
```
Redis 单线程模型保证原子性，适合分布式限流。

---

## 三、记忆系统类

### Q8: 短期记忆和长期记忆的边界？怎么实现？

**答**：
- **短期**（checkpointer）：本次对话（thread）内的状态，LangGraph 按 thread_id 保存每步状态快照。对话结束即可清理。开发用 MemorySaver，生产用 PostgresSaver。
- **长期**（store）：跨对话的用户信息，按 namespace `("user", user_id)` 隔离，支持语义检索。用 InMemoryStore（开发）/ PostgresStore（生产）。

边界是 thread_id：同一 thread 续接短期上下文；跨 thread 但同 user_id 共享长期记忆。

### Q9: 语义检索为什么需要 embedding？你的哈希 embedding 有什么问题？

**答**：embedding 把文本映射到向量空间，语义相近的文本向量距离近，从而支持"按意思"检索（"编程偏好"能匹配"喜欢写代码"）。

哈希 embedding 的问题：它是字符级哈希，**没有语义理解**——"猫"和"狗"的向量不会比"猫"和"汽车"更近。开发期能让接口跑通，但检索质量差。生产必须换真实 embedding（如 text-embedding-3-small），它在大规模语料上预训练，能捕捉语义。

### Q10: 用户画像为什么用 Neo4j 不用 Postgres？

**答**：画像是**实体-关系网络**，核心查询是多跳关系遍历（如"用户朋友也感兴趣的话题"——2跳查询）。关系型数据库的 JOIN 每多一跳开销指数增长，3跳以上基本不可用。Neo4j 用邻接表存储，关系遍历每跳 O(1)。这是 polyglot persistence（多语言持久化）——每个数据用最适合它的存储。

### Q11: 记忆和画像怎么注入对话的？

**答**：`run_agent` 时动态构造系统提示：
1. 基础提示 + Skill 提示词
2. 用语义检索取与当前问题最相关的 top-3 长期记忆
3. 查用户画像的兴趣/偏好
三者拼进 system message，LLM 综合后个性化回答。失败时静默跳过，不阻断对话。

---

## 四、协议类（LLM / MCP / A2A）

### Q12: OpenAI 和 Anthropic 协议有哪些具体差异？

**答**：四处关键差异（都在 provider 实现里封装了）：
1. **system 位置**：OpenAI 混在 messages 里；Anthropic 是顶层参数
2. **工具调用格式**：OpenAI 用 `tool_calls`+`role:tool`；Anthropic 用 content blocks（`tool_use`/`tool_result`），且结果放 user 角色
3. **arguments 类型**：OpenAI 是 JSON 字符串需 parse；Anthropic 是已解析 dict
4. **usage 字段**：OpenAI 是 prompt/completion_tokens；Anthropic 是 input/output_tokens 无 total

### Q13: GLM 为什么能走 OpenAI 兼容协议？

**答**：智谱暴露了完全 OpenAI 兼容的 `/chat/completions` 端点（`https://open.bigmodel.cn/api/paas/v4/`），请求/响应格式、工具调用、流式、usage 全部一致。只需把 openai SDK 的 `base_url` 换掉、`api_key` 用智谱的。这样 GLM、OpenAI、DeepSeek、Moonshot 等 OpenAI 兼容的 provider 共用一份代码。

### Q14: MCP 和 A2A 的本质区别？

**答**：
- **MCP**（agent↔tool）：调用**被动的工具**（函数），工具没有自主性。解决"工具接口标准化"。
- **A2A**（agent↔agent）：协作**有自主性的 Agent**（有自己的 LLM/记忆/工具），是对等的。解决"Agent 互通"。
互补关系：一个 Agent 可同时是 A2A server（被调用）+ A2A client（调别人）+ MCP client（用工具）。

### Q15: 你的 A2A delegate_to_agent 工具有什么安全风险？

**答**：主要风险：
1. **信任**：外部 Agent 输出质量/安全不可控 → 加白名单、输出校验
2. **可用性**：外部 Agent 宕机 → 已有 60s 超时
3. **数据泄露**：委托时可能泄露敏感信息 → 脱敏后再委托
4. **成本**：无限委托循环 → recursion_limit 限制

### Q16: mcp 2.0 出来时为什么先锁 <2.0，后来又是怎么迁的？

**答**：分两步。
1. **2026-07 先锁**：mcp 2.0 随 2026-07-28 规范大版本发布，但官方桥接 `langchain-mcp-adapters 0.3.1` 仍用 mcp 1.x 的 `RequestContext`，强行上 2.0 会导入崩溃。所以写成 `mcp>=1.24.0,<2.0`，上限挡住破坏性变更，注释写明「在等桥接适配」。
2. **2026-09 迁移**：adapters 仓库归档（2026-09-17），桥接并入 langchain 主包 `langchain.mcp`（`langchain[mcp]` extra，底层 fastmcp 4.x + mcp 2.x）。生态就绪后解锁：client 从 `MultiServerMCPClient` 换成 `MCPAdapter`，server 从 `mcp.server.fastmcp` 换成独立的 `fastmcp` 包，约束改为 `mcp>=2.0.0,<3.0`。迁移时还顺手修掉了 server 侧「`**kwargs` 包装导致注册出无参工具」的隐患。

**追问点**：锁版本要有出口——上界 + 注释写清「为什么锁、等什么解锁」，条件满足就迁。锁是为了不被 resolver 推着跨 breaking 版本，不是为了永远不升级。

---

## 五、工程化类

### Q17: 数据库连不上时为什么不崩溃？

**答**：**优雅降级**。开发期常见容器没起。`db_manager` 对每个连接 try/except，失败只告警不抛异常。这样 LLM 对话（用 MemorySaver 不依赖 DB）仍可用。生产中也保证核心链路尽量独立于非关键依赖——这是韧性设计。

### Q18: 配置和密钥怎么管理？

**答**：
- pydantic-settings 从环境变量 / .env 读取，**类型安全**
- `.env` 在 `.gitignore`，绝不提交
- `.env.example` 提供模板（占位值）
- 代码零硬编码密钥，全走 `get_settings()` 单例
- 生产用环境变量注入（K8s Secret / Vault），不落盘

### Q19: 怎么保证代码质量？

**答**：
- **类型注解**全程 + pydantic 校验
- **多层测试**：190 条收集用例（单元/契约/安全边界/性能回归），全套约 6s，零外部依赖（conftest 把四个数据库指向黑洞端口）
- **验证脚本** per Phase（verify_phaseN.py），无 DB/key 也能验核心逻辑
- **ruff** lint + 格式化
- **结构化日志** + trace_id 全链路追踪
- **统一异常处理**：业务异常→标准 JSON 响应

### Q20: 怎么做可观测性？

**答**：
- **结构化日志**：每条含 trace_id（每请求生成），可串起全链路
- **对话日志**：MongoDB 记录每轮事件（输入/输出/工具/token/耗时），可审计
- **token 统计**：LLM 响应带 usage，可算成本
- **OpenTelemetry 已接入**：`app/core/telemetry.py` 全套 span 体系（`agent.turn` / `context.build` / `llm.chat` / `tool.execute`，GenAI 语义约定命名），OTLP 导出到 Jaeger，`OTEL_ENABLED` 开关

### Q21: 如果让你加一个"对话总结"功能，怎么做？

**答**：两个层面：
1. **单会话总结**：当消息超过阈值时，用一个轻量 LLM 把历史总结成一段，压缩上下文。LangGraph 可加一个 `summarize` 节点，条件触发（消息数 > N）。
2. **跨会话沉淀**：会话结束时，抽取关键事实写入长期记忆（store）和画像（Neo4j）。下次该用户对话自动检索。这实现了"Agent 越用越懂用户"。

### Q22: 项目里你最得意的设计是什么？

**答**：**统一工具注册表（registry）**。它把三个来源（内置 @tool、MCP 远程工具、Skill 工具）汇聚成单一真相来源，tools_node 只从这里查找。结果：
- 新增任何来源的工具，执行路径完全一致
- 加 MCP 不改 tools_node，加 Skill 不改 MCP
- 符合开闭原则：对扩展开放，对修改封闭

这是整个架构"可扩展性"的基石。

### Q23: 用户认证和多租户是怎么集成进来的？要重构核心吗？

**答**：不用重构。认证和租户加在**新增的业务层与中间件层**，核心能力层一行没改：
- API 层用 FastAPI 的 `Depends(get_current_user)` 注入已验证身份
- `tenant_id` 从 JWT claims 解出（不可伪造），传给下游
- 记忆 namespace 加租户前缀、会话查询加 tenant 过滤

核心层只认 user_id 字符串，从不感知认证——这就是当初分层的目的：业务逻辑变化不波及核心。

### Q24: RAG 为什么复用 PostgresStore 而不用 Pinecone/Milvus？

**答**：① 复用已有基础设施，零额外运维成本；② PostgresStore 的 `index` 配置支持语义检索，中小规模（万级文档）够用；③ BaseStore 抽象隔离了实现，将来要换专用向量库只换底层、接口不变。本质是"用合适的复杂度解决当前规模的问题"。

### Q25: RAG 分块为什么要重叠？

**答**：句子可能在块边界被切断。重叠（50 字符）让相邻块共享一小段，被切断的句子在下一块仍完整，检索时不丢上下文。这是 chunking 标准实践。块大小（500）和重叠（50）是经验值，不同场景需调优。

### Q26: Hermes 自我进化的反思会不会越改越差？怎么防？

**答**：三道保险：① **评分阈值**——自评低于 6 分不自动采纳；② **版本管理**——每次优化存新版本，可一键回滚；③ **手动触发**——反思不是自动循环，需主动调 `/evolution/reflect`，不会无限自我修改。

### Q27: 限流组件故障了怎么办？

**答**：**放行**。限流是"防滥用"的辅助措施，不是核心功能。Redis 不可用时若拒绝所有请求，反而造成服务不可用——违背"核心链路独立于非关键依赖"的韧性原则。这是 fail-open 设计。

### Q28: 这个项目如果上生产，还需要补什么？

**答**：架构已具备生产基线，还差运维侧：
- **HTTPS/反代**：Nginx + TLS（代码已支持）
- **容器编排**：K8s + Helm（应用无状态，可水平扩）
- **分布式追踪**：✅ 已接 OpenTelemetry（span 树 + Jaeger），生产补采样策略与告警即可
- **真实 embedding**：RAG/记忆的哈希 embed 换成真实模型
- **告警**：基于 /metrics 配 Prometheus + AlertManager
- **CI/CD**：已有测试基础，加 GitHub Actions 自动化

这些是运维/配置层面，不涉及核心架构改动。

---

## 附：快速自查清单

面试前能脱口而出的要点：

- [ ] 五层架构 + 依赖方向
- [ ] ReAct 循环流程（agent→tools→agent）
- [ ] 短期 vs 长期记忆的实现与边界
- [ ] OpenAI vs Anthropic 四处差异
- [ ] GLM 走 OpenAI 兼容的原因
- [ ] MCP vs A2A 区别
- [ ] 为什么 Postgres 不是 MySQL
- [ ] 为什么 Neo4j 存画像
- [ ] 优雅降级的设计
- [ ] async 的必要性
