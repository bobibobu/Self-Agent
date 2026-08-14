# 记忆系统

> 短期记忆 + 长期记忆 + 对话日志，三层记忆体系让 Agent 既记得"刚才说的话"，也记得"这个用户的偏好"。

---

## 一、为什么 Agent 需要记忆？

没有记忆的 LLM 是「金鱼」——每次对话都从零开始。真实场景需要：

| 场景 | 需要的记忆 |
|---|---|
| "我刚才说的那件事" | **短期记忆**（本次对话内） |
| "用户喜欢简洁回答" | **长期记忆**（跨对话） |
| "上周聊了什么" | **对话日志**（历史回溯） |
| "用户是 Python 开发者" | **用户画像**（结构化属性） |

---

## 二、三层记忆体系

### 1. 短期记忆（Short-Term / Checkpointer）

**作用**：单次对话（thread）内的上下文连续性。

**实现**：LangGraph 的 checkpointer，按 `thread_id` 保存状态快照。

| 后端（`STORAGE_BACKEND=auto` 默认） | 实现 | 特点 |
|---|---|---|
| 优先 | `AsyncPostgresSaver` | Postgres 持久化，跨进程共享 |
| 回退（连不上时，日志 WARNING） | `MemorySaver` | 内存，重启丢失 |
| CLI 本地模式 | SQLite（按工作区哈希分库） | 单机持久化 |

```python
# 同 thread_id 自动续接上下文
POST /chat {"message":"我叫小明", "thread_id":"t1"}
POST /chat {"message":"我叫什么？", "thread_id":"t1"}  # → "小明"
POST /chat {"message":"我叫什么？", "thread_id":"t2"}  # → 不知道（新会话）
```

**文件**：`app/memory/checkpointer.py`

### 2. 长期记忆（Long-Term / Store）

**作用**：跨会话记住用户的事实与偏好，支持**语义检索**。

**实现**：LangGraph 的 BaseStore，按 namespace（`("user", user_id)`）隔离。

| 后端 | 实现 | embedding |
|---|---|---|
| PG 可用 | `AsyncPostgresStore` | 配了 API key 用真实 embedding |
| PG 不可用（回退） | `InMemoryStore` | 未配 key 时降级为哈希伪向量（检索失去语义，日志 WARNING） |

```python
# 添加记忆
POST /memory {"user_id":"u1", "content":"用户偏好简洁技术回答"}

# 语义检索（按相似度排序）
GET /memory/u1?query=用户的回答风格偏好
# → 命中"用户偏好简洁技术回答"
```

**语义检索原理**：文本经 embedding 转成向量，查询时算余弦相似度排序。
是否真实 embedding 取决于**有无 API key**（`auto` 跟随 LLM provider），与开发/生产环境无关：
配了 key 走真实向量化；没配降级为确定性哈希伪向量（零依赖但无语义）。

**文件**：`app/memory/store.py`、`app/memory/store.py:MemoryService`

### 3. 对话日志（Conversation Log）

**作用**：记录每轮对话的完整事件（输入/输出/工具/耗时/token），用于审计与分析。

**实现**：MongoDB（形态多变、写多读少，适合无 schema）。

设计为「即发即忘」：日志记录失败**不影响对话主流程**。

```python
GET /history/t1  # → 该会话的对话历史
```

**文件**：`app/logging_service/__init__.py`

---

## 三、记忆如何注入对话？

`run_agent` 时，系统提示词动态拼接三层信息：

```
基础系统提示
  + Skill 提示词片段（Phase 2）
  + 用户长期记忆（语义检索 top-3）      ← 长期记忆
  + 用户画像（兴趣/偏好）              ← 结构化属性
```

这样 LLM 在回答时，既能参考历史记忆，又能根据用户画像个性化响应。

---

## 四、长期记忆 vs 用户画像

容易混淆，二者互补：

| 维度 | 长期记忆 | 用户画像 |
|---|---|---|
| 数据形态 | 自由文本 | 结构化实体-关系 |
| 查询方式 | 语义检索（模糊） | 精确匹配 |
| 存储 | Store（Postgres/内存） | Neo4j 图数据库 |
| 例子 | "用户提过在做微服务" | `(用户)-[:INTERESTED_IN]->(微服务)` |
| 适用 | 对话式回忆 | 属性化分析 |

详见 [用户画像文档](06-user-profile.md)。

---

## 五、面试要点

**Q: 短期记忆和长期记忆的边界在哪？**
A: 短期是「本次对话」的上下文（checkpointer，按 thread），长期是「跨对话」的用户信息（store，按 namespace）。短期对话结束即可丢弃，长期需要跨会话持久化。

**Q: 语义检索为什么需要 embedding？**
A: 关键词匹配无法理解语义（"编程偏好" ≠ "写代码喜欢"但语义相近）。embedding 把文本映射到向量空间，相似语义的向量距离近，从而支持"按意思"而非"按字面"检索。

**Q: 哈希 embedding 为什么只在开发用？**
A: 它是确定性的字符哈希，没有真实语义理解能力（"猫"和"狗"的向量不会比"猫"和"汽车"更近）。开发期能让接口跑通即可；生产必须用真实 embedding 模型（捕捉语义）。
