# 第 1 章：AutoGPT —— 自主循环的源头与教训

> github.com/significant-gravitas/autogpt，~185k star（GitHub 史上增长最快仓库之一，2023 年 3 月发布）。
> **「自主 Agent」概念的源头**。历史意义 > 工程价值。

---

## 1.1 它是什么

2023 年 3 月发布，GitHub 史上增长最快的仓库之一（~185k star）。同类还有 AgentGPT（浏览器无代码版）、BabyAGI（任务列表驱动版）。

它开创了「**自主 Agent**」这个品类——给个目标，agent 自己跑到底。

---

## 1.2 核心设计：self-prompting 循环

模型**自己给自己生成下一步任务**，无需人持续干预。这是「自主 Agent」概念的源头。

```
目标 → 拆任务 → 执行 → 观察结果 → 更新任务列表 → 重复
```

这是 **Plan-and-Execute 的早期原型**（全书第 14 章）。

### 和 ReAct 的区别

- **ReAct**：每步在人监督下，工具调用前可能审批
- **self-prompting**：无人监督，agent 自己决定下一步干什么、干多久

AutoGPT 的循环没有「人在回路」——它信任 agent 的自主性。

---

## 1.3 BabyAGI 的任务列表 + 优先级（标志性设计）

BabyAGI（Yohei Nakajima）的标志性设计，三个核心函数：

- `create_task`：根据观察创建新任务
- `prioritize_task`：重新排序任务优先级
- `execute_task`：执行最高优先级任务

```
循环：
  1. 执行最高优先级任务
  2. 观察结果
  3. 根据结果创建新任务（可能多个）
  4. 重新排序所有任务优先级
  5. 回到 1
```

### 这个简单结构的价值

「任务列表 + 优先级」这个简单结构，**至今仍是 Plan-and-Execute 的骨架**。

- Aider 的 Architect 模式隐含任务列表
- Cline 的 Plan 模式产出任务列表
- **Self-Agent 的 `update_plan` 是它的简化版**（但有约束：同一时刻一个 in_progress、recursion_limit）

---

## 1.4 长期记忆 + 文件系统 workspace

- **长期记忆**：用向量库存历史（这是 RAG 的早期应用）
- **文件系统作为工作区**：AutoGPT 把中间产物落地到 workspace 目录

这两个设计后来都被广泛采用：
- 向量库记忆 → 现在 RAG 的标配
- 文件 workspace → 编码 Agent 的工作区概念（Self-Agent 的 Workspace）

---

## 1.5 ★ 教训：无约束自主性的灾难

AutoGPT 证明了自主循环**可行**，但暴露了根本问题：

### 跑偏

没有约束，agent 容易钻牛角尖或偏离目标。给它「研究如何赚钱」，它可能花一晚上在「如何写一个赚钱的网站」上打转。

### 死循环

陷入「调同一个工具 → 失败 → 再调」的循环，烧掉大量 token。

### 烧钱

无人值守 = 无限 token 消耗。用户睡一觉醒来账单爆炸。

### 这正是为什么后来转向约束式

后来的编码 Agent（Claude Code、Self-Agent）都强调约束：
- **Self-Agent 的 `recursion_limit`**（防死循环）
- **审批闸门**（人在回路纠偏）
- **沙箱**（限制破坏范围）
- **预算控制**（虽然 Self-Agent 还没显式做，但是方向）

---

## 1.6 历史价值 > 工程价值

AutoGPT 现在看代码粗糙，但历史意义是**开创了「自主 Agent」这个品类**：

1. **证明了自主循环可行**：LLM 能自己拆任务、自己执行、自己调整
2. **任务列表+优先级的简单结构至今有用**：BabyAGI 的设计是 Plan-and-Execute 的骨架
3. **暴露了无约束自主性的问题**：催生了后来的约束式 Agent

没有 AutoGPT 的「失败」，就不会有 Claude Code/Self-Agent 的「成功」——它们都是对 AutoGPT 教训的回应。

---

## 1.7 给 Self-Agent 的启示

### 启示①：update_plan 可加优先级

Self-Agent 的 update_plan 是 BabyAGI 任务列表的简化继承，但**没有优先级排序**。可借鉴 BabyAGI，让模型给任务标优先级，多任务时知道先做哪个。

### 启示②：显式的预算/步数控制

AutoGPT 烧钱的教训说明：自主循环必须有显式的预算控制。Self-Agent 有 recursion_limit（步数控制），但**没有 token 预算控制**。可加一个「单次任务最多花多少 token」的限制。

### 启示③：约束是必需品不是可选项

AutoGPT 的失败证明：自主性没有约束就是灾难。Self-Agent 的三层安全 + recursion_limit + 审批是对的——这些不是「限制 agent 能力」，是「让 agent 可用」。

---

## 1.8 事实声明

- ~185k star：2023 年发布时增长最快
- self-prompting 循环、任务列表+优先级：AutoGPT/BabyAGI 官方
- 架构拆解：Medium 技术分析
- 教训分析：基于实际使用观察的共识

→ [下一章：MetaGPT](02-MetaGPT.md)
