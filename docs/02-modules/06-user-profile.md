# 用户画像

> 基于 Neo4j 图数据库的结构化用户画像，记录兴趣、偏好、属性。

---

## 一、为什么用图数据库？

用户画像是**实体与关系的网络**：

```
(用户:小明)-[:INTERESTED_IN]->(话题:编程)
(话题:编程)-[:RELATED_TO]->(技能:Python)
(用户:小明)-[:PREFERS]->(风格:简洁回答)
(用户:小明)-[:WORKS_AS]->(角色:后端工程师)
```

这类「多跳关系查询」用关系型数据库的 JOIN 会随深度变慢（O(n^深度)），
而图数据库用邻接表存储，关系遍历是 O(1) 每跳，天然适合。

---

## 二、数据模型

### 节点（Node）

| 标签 | 属性 | 用途 |
|---|---|---|
| `User` | `id`（主键）+ 自定义属性 | 用户实体 |
| `Topic` | `name` | 兴趣话题 |
| `Preference` | `key`, `value` | 偏好项 |

### 关系（Relationship）

| 关系 | 方向 | 含义 |
|---|---|---|
| `INTERESTED_IN` | User → Topic | 用户对某话题感兴趣 |
| `PREFERS` | User → Preference | 用户偏好某设置 |

---

## 三、API

```python
# 记录兴趣
POST /profile/interest {"user_id":"u1", "interest":"人工智能"}

# 记录偏好
POST /profile/preference {"user_id":"u1", "key":"回答风格", "value":"详细"}

# 获取完整画像
GET /profile/u1
# → {interests:["人工智能"], preferences:{"回答风格":["详细"]}, source:"neo4j"}
```

---

## 四、优雅降级

Neo4j 不可用时（开发期容器没起），自动用内存 dict 兜底：

```python
class ProfileService:
    def _ensure_neo4j(self) -> bool:
        if db_manager.neo4j is not None:
            return True  # 用 Neo4j
        return False     # 用内存兜底
```

`source` 字段标识数据来源（`neo4j` / `memory_fallback`），便于调试。

---

## 五、Cypher 查询示例

```cypher
-- 找对该话题感兴趣的用户
MATCH (u:User)-[:INTERESTED_IN]->(t:Topic {name:'编程'})
RETURN u.id

-- 找用户的二度相关话题（朋友也感兴趣的）
MATCH (u:User {id:'u1'})-[:INTERESTED_IN]->(:Topic)<-[:INTERESTED_IN]-(friend)-[:INTERESTED_IN]->(rec:Topic)
WHERE rec.name <> '编程'
RETURN DISTINCT rec.name
```

后者（推荐）是图数据库的经典应用：基于关系网络做推荐。

---

## 六、与长期记忆的协作

画像与记忆在 `run_agent` 中共同注入系统提示：

```
【关于该用户的长期记忆】        ← 自由文本（语义检索）
- 用户在学 LangGraph
- 用户偏好简洁回答

【用户画像】                    ← 结构化属性
兴趣：人工智能、系统设计
偏好：回答风格=详细
```

LLM 综合两者，给出个性化回答。

---

## 七、面试要点

**Q: 用户画像为什么单独用 Neo4j，不用 Postgres？**
A: 画像是「实体-关系」密集型数据，核心查询是多跳关系遍历（如"朋友也感兴趣的话题"）。Postgres 的 JOIN 在 3 跳以上性能急剧下降，Neo4j 的图遍历每跳 O(1)。各数据库用在其强项，这是多语言持久化（polyglot persistence）思想。

**Q: 画像数据怎么更新？显式 API 还是自动学习？**
A: 当前是显式 API（调用方主动记录）。进阶可让 Agent 在对话中自动抽取——用一个轻量 LLM 从对话流中识别"兴趣/偏好"事实，再写入画像。这是 Phase 后续可扩展点。
