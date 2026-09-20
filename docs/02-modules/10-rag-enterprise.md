# RAG 知识库与企业能力

> RAG 检索增强 + 文件上传 + 用量统计 + 可观测，补齐成熟 Agent 的企业级能力。

---

## 一、RAG 知识库（Retrieval-Augmented Generation）

### 解决什么问题
LLM 只知道预训练数据。要让 Agent 基于你的**私有文档**回答（产品手册、内部知识、FAQ），就需要 RAG。

### 流程（2026-09 升级后）
```
上传文档 → 分块（滑动窗口，可选 contextual 前缀增强）→ 向量化 → 存入向量库
                                                              ↓
对话时 → ①系统提示注入检索（原路径，kb_ids 自动）        → LLM 结合资料回答
        ②search_knowledge_base 工具（Agentic RAG，模型按需调用，可多轮迭代）
```

### Hybrid 检索（向量 + 关键词，RRF 融合）
原实现只有单路向量检索——孤立 chunk 脱离原文语境，专有名词/代号/编号这类
「精确字面」查询经常排不进 top-k。现在检索走两条通道：

- **向量通道**：`store.asearch(query=...)`，语义相近但字面不同的块
- **关键词通道**：直接查 PostgresStore 的 `store` 表（prefix 等值定位本知识库，
  `value->>'content'` 上 ILIKE 子串命中；CJK 查询切二元 bigram，
  「机器学习」→ 机器/器学/学习，命中数天然构成相关度）
- **融合**：Reciprocal Rank Fusion（RRF，k=60），两路排名取 `1/(k+rank)` 累加

Postgres 不可用时自动退化为纯向量检索（升级前行为），检索结果带
`match: ["dense", "keyword"]` 标记命中通道，便于观测。

### Contextual 分块（Anthropic Contextual Retrieval 思路）
入库时用 LLM 给每块生成一句「该片段讲什么、在文档中的位置」前缀，与原块
拼接后再向量化——embedding 看到的是「有上下文的块」而非孤立段落。

- 每块一次 LLM 调用：并发上限 8（`_CONTEXTUAL_CONCURRENCY`），总量帽
  `RAG_CONTEXTUAL_MAX_CHUNKS`（默认 64），单块失败回退原始块，绝不阻断入库
- **GLM 4.5 系列必须关思考模式**（`extra_body={"thinking":{"type":"disabled"}}`）：
  推理模型的思考 token 会把一个 150 token 的小任务拖到 45s+ 超时
- 存储字段：`content`=增强后文本（被向量化），`raw`=原始块

### Agentic RAG（检索即工具）
`search_knowledge_base` 注册为内置只读工具，模型自主决定何时检索、用什么
query、要不要再检索一轮——把「每轮固定注入」的成本变成按需付出。

- 知识库范围从图 config 的 `configurable` 注入（`kb_ids`/`tenant_id`，
  见 `graph.py`），工具不接受 kb_ids 参数，模型无法越权检索未关联的知识库
- 工具执行链路：`tools_node` 现在把图 config 传给 `tool.ainvoke(args, config=...)`，
  声明了 `RunnableConfig` 参数的工具自动拿到请求级上下文

### 实现（复用已有基础设施）
- **向量库**：复用 PostgresStore/InMemoryStore 的语义索引（`index={"embed":...}`）
- **分块**：滑动窗口，500 字符/块，50 字符重叠（保上下文连贯）
- **隔离**：每个知识库一个 namespace `("kb", kb_id)`，多租户启用时带租户前缀

### 端点
| 端点 | 说明 |
|---|---|
| `POST /rag/kb/{kb_id}` | 上传文档（自动分块+入库，可选 contextual 增强） |
| `GET /rag/kb/{kb_id}/search?query=` | Hybrid 检索（向量+关键词 RRF 融合） |
| `DELETE /rag/kb/{kb_id}` | 删除知识库 |
| `POST /chat` 带 `kb_ids` | 对话时自动检索注入 + `search_knowledge_base` 工具按需检索 |

### 配置
| 环境变量 | 默认 | 说明 |
|---|---|---|
| `RAG_HYBRID_SEARCH` | `true` | 关键词通道开关（Postgres 不可用自动退化） |
| `RAG_CONTEXTUAL_CHUNKING` | `true` | 入库时 LLM 生成块上下文前缀（无 key 自动跳过） |
| `RAG_CONTEXTUAL_MAX_CHUNKS` | `64` | 单次 ingest 最多增强的块数 |
| `RAG_CONTEXTUAL_MODEL` | 空 | 增强用的模型（留空跟随默认模型） |

### 用法
```bash
# 1. 上传知识库
curl -X POST http://localhost:8000/rag/kb/product-doc \
  -H "Content-Type: application/json" \
  -d '{"content": "我们的产品 X 支持...", "source": "产品手册"}'

# 2. 带知识库对话
curl -X POST http://localhost:8000/chat \
  -d '{"message": "产品X支持什么功能？", "kb_ids": ["product-doc"]}'
```

---

## 二、文件/图片上传

### 端点
- `POST /upload`：上传文件（multipart/form-data）
  - 文本类（txt/md/json/csv/py 等）：提取内容，可 `auto_ingest=true` 自动入 RAG
  - 图片类（png/jpg）：存储，返回访问 URL
- `GET /uploads`：列出已上传文件（**仅管理员**——上传目录未按租户/用户分区，列表会暴露所有用户的文件名）

### 安全
- 大小限制 `UPLOAD_MAX_SIZE_MB`（默认 20MB）
- 文件名加 uuid 前缀防重名/路径穿越

---

## 三、用量统计

### 端点
`GET /stats/usage?user_id=&days=7`

返回：总请求数、token 用量（prompt/completion/total）、成本估算、错误数、按天分布。

### 成本估算
内置价格表（GLM-4.5-flash 免费，GPT-4o/Claude 按公开定价）。未知模型用保守默认价。

---

## 四、可观测（/metrics）

### 端点
`GET /metrics`（**仅管理员**）

返回运行时指标：
- 运行时长、总请求数
- 按路径+状态码的请求计数
- 平均响应延迟
- 基础设施连通性（4 个 DB + checkpointer 持久化状态）

### 实现
轻量内置采集（MetricsMiddleware），不依赖 Prometheus。大规模可换 prometheus_client + OpenTelemetry。

---

## 五、完整企业能力对照

经过 Phase 7-8，本项目已对齐成熟 Agent 的核心能力：

| 能力 | 状态 |
|---|---|
| 真·token 流式（SSE + NDJSON） | ✅ |
| 多协议 LLM（GLM/OpenAI/Anthropic） | ✅ |
| 工具调用 + MCP + A2A | ✅ |
| 短期/长期/画像/日志 记忆 | ✅ |
| Hermes 自我进化 | ✅ |
| 会话管理（CRUD + 持久化） | ✅ |
| 上下文压缩 + 流式中断 | ✅ |
| 用户认证 + 多租户 | ✅ |
| 限流 + 用量统计 + 可观测 | ✅ |
| RAG 知识库 | ✅ |
| 文件/图片上传 | ✅ |

---

## 六、面试要点

**Q: RAG 为什么复用 PostgresStore 而不用专门的向量库（如 Pinecone/Milvus）？**
A: ① 复用已有基础设施，零额外运维；② PostgresStore 支持语义索引，中小规模够用；③ 中小知识库（万级文档）pgvector 性能足够。规模到百万级向量再换专用向量库，接口不变（BaseStore 抽象）。

**Q: RAG 分块为什么要重叠？**
A: 句子可能被切断在块边界。重叠（50 字符）让相邻块共享一小段，被切断的句子在下一块仍是完整的，检索时不丢上下文。这是 chunking 的标准实践。

**Q: 成本统计的准确性如何？**
A: token 数精确（来自 LLM 响应 usage），成本是**估算**（按内置价格表 × token）。精确成本需对接各 provider 的实际计费 API，这里给的是可接受的近似值，用于趋势监控而非对账。
