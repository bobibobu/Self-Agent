# RAG 知识库与企业能力

> RAG 检索增强 + 文件上传 + 用量统计 + 可观测，补齐成熟 Agent 的企业级能力。

---

## 一、RAG 知识库（Retrieval-Augmented Generation）

### 解决什么问题
LLM 只知道预训练数据。要让 Agent 基于你的**私有文档**回答（产品手册、内部知识、FAQ），就需要 RAG。

### 流程
```
上传文档 → 分块（chunking）→ 向量化（embedding）→ 存入向量库
                                                    ↓
对话时 → 按问题语义检索相关块 → 注入提示词 → LLM 结合资料回答
```

### 实现（复用已有基础设施）
- **向量库**：复用 PostgresStore/InMemoryStore 的语义索引（`index={"embed":...}`）
- **分块**：滑动窗口，500 字符/块，50 字符重叠（保上下文连贯）
- **隔离**：每个知识库一个 namespace `("kb", kb_id)`

### 端点
| 端点 | 说明 |
|---|---|
| `POST /rag/kb/{kb_id}` | 上传文档（自动分块+入库） |
| `GET /rag/kb/{kb_id}/search?query=` | 语义检索 |
| `DELETE /rag/kb/{kb_id}` | 删除知识库 |
| `POST /chat` 带 `kb_ids` | 对话时自动检索增强 |

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
