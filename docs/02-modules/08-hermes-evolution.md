# Hermes 自我进化（Self-Evolution）

> 让 Agent 随使用越来越聪明——两大能力：被动记忆画像学习 + 主动反思提示词优化。

---

## 一、设计目标

普通 Agent 用完即弃，不积累。Hermes 让 Agent 具备「自我进化」：

| 能力 | 类型 | 触发 | 效果 |
|---|---|---|---|
| A. 自动记忆画像学习 | 被动 | 每轮对话后 | 越用越懂用户 |
| B. 反思+提示词自优化 | 主动 | 手动/定期 | 越用回答越好 |

---

## 二、能力 A：自动记忆画像学习

**流程**：对话结束 → 异步用轻量 LLM 抽取「值得记住的事实」→ 写入画像/记忆

```
对话 "我在学AI，是Python开发者，喜欢详细回答"
  ↓ (异步，fire-and-forget)
LLM 抽取 → {"interests":["AI"], "preferences":{"风格":"详细"}, "facts":["Python开发者"]}
  ↓
兴趣 → Neo4j 用户画像
偏好 → Neo4j 用户画像
事实 → Store 长期记忆
```

抽取用结构化 JSON 输出，确保可解析、可控。**不干扰主对话**——异步触发，失败只记日志。

**文件**：`app/evolution/memory_learner.py`

---

## 三、能力 B：反思 + 提示词自优化

**流程**：取近期对话样本 → LLM 自评当前提示词表现 → 生成优化版 → 存版本（可回滚）

```
POST /evolution/reflect
  ↓
取 MongoDB 近 5 轮对话样本
  ↓
LLM 反思："当前提示词下回答质量 8/10，问题：不够简洁、工具说明少"
  ↓
生成优化版提示词
  ↓
评分 >= 阈值(6.0)？→ 存为新版本（可回滚）
```

**安全设计**：
- 不直接覆盖，每次存新版本（`data/prompts/v{timestamp}.json`）
- 评分低于阈值不自动采纳（防越改越差）
- 可随时回滚：`POST /evolution/rollback/{version}`

**文件**：`app/evolution/reflector.py` + `app/evolution/prompt_store.py`

---

## 四、提示词版本管理

```python
get_current_prompt()     # 当前生效版本（无版本时回退内置默认）
save_version(content)    # 存新版本
list_versions()          # 列历史版本
rollback(version)        # 回滚
```

系统提示词从 prompt_store **动态读取**（`graph.py:_build_system_message`），Hermes 优化后下次对话自动生效。

---

## 五、API 端点

| 端点 | 方法 | 说明 |
|---|---|---|
| `/evolution/reflect` | POST | 手动触发反思循环 |
| `/evolution/prompt` | GET | 查看当前提示词+版本 |
| `/evolution/versions` | GET | 列出历史版本 |
| `/evolution/rollback/{version}` | POST | 回滚到指定版本 |

---

## 六、配置开关

```ini
HERMES_LEARNING_ENABLED=true     # 能力A：自动学习（默认开）
HERMES_REFLECTION_ENABLED=true   # 能力B：反思优化（默认开）
```

关闭后 Agent 退化为普通无进化模式，不影响核心功能。

---

## 七、为什么叫 Hermes？

Hermes（赫尔墨斯）是希腊神话中「信使与智慧之神」，象征「不断学习、传递进化」。本模块让 Agent 像赫尔墨斯一样，在每次交互中积累智慧。

---

## 八、面试要点

**Q: 自我进化的最大风险是什么？怎么控制？**
A: ① **提示词退化**——反思可能越改越差。控制：评分阈值（低于6不采纳）+ 版本管理（随时回滚）+ 不会无限自改（手动触发）。② **记忆污染**——学到错误信息。控制：抽取只记「稳定事实」，对话日志全留可审计。③ **成本**——额外 LLM 调用。控制：学习能力用轻量模型/低参数，异步不阻塞。

**Q: 被动学习会不会学到用户随口说的话？**
A: 有这个风险。抽取提示词强调「只抽明确的、稳定的信息」，且记入前可加置信度过滤。进阶可让用户查看/删除记忆（已有 `/memory/{id}/all` 和 DELETE 端点）。这是可记忆性与隐私的平衡。

**Q: 反思用 LLM 自评，LLM 能客观评价自己吗？**
A: 不完全能（自评有偏差）。但反思的价值在于「显式化隐含问题」——即便评分不完美，它指出的改进方向（如"工具说明不够"）通常有参考价值。生产可引入人工审核环节：反思生成候选版本，人工确认后才采纳。
