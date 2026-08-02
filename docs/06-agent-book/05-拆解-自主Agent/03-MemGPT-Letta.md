# 第 3 章：MemGPT / Letta —— 虚拟内存式上下文管理

> MemGPT（论文 Packer et al. 2023）→ 产品化 Letta。
> **仿操作系统的虚拟内存分页**——主上下文 + 归档层，agent 自己 page in/out，自编辑。
> 这是记忆领域「思想最超前」的方案。

---

## 3.1 它是什么

MemGPT 是 UC Berkeley 2023 年的论文（Packer et al.），灵感来自**操作系统的虚拟内存**。后来产品化成 **Letta**（前名 MemGPT）。

核心思想：把 LLM 的上下文窗口类比为「内存」，外部存储类比为「磁盘」，让 agent **自己管理**上下文的 page in/out。

---

## 3.2 核心思想：OS 启发的上下文管理

```
┌─────────────────────┐
│ 主上下文（内存）      │ ← LLM 直接看到的有限窗口
│  - system prompt     │   （系统提示、关键事实、最近对话）
│  - core memory       │   agent 能直接读写
│  - working context   │
├─────────────────────┤
│ 归档层（磁盘）        │ ← 外部存储
│  - 历史对话           │   agent 按需 page in
│  - 长期记忆           │
└─────────────────────┘
```

### 类比 OS 的页面调度

- OS：内存有限，把不常用的页面换出到磁盘（swap），需要时再换入（page in）
- MemGPT：上下文有限，把不常用的对话/记忆换出到归档层，需要时再换入

**关键区别**：MemGPT 的 agent **自己决定**什么时候换什么——像 OS 的页面调度，但是 agent 自己当调度器。

---

## 3.3 自编辑（self-editing）

agent 能**修改自己的 core memory**——把重要事实写进主上下文的固定区域，下次直接看到。

### 怎么工作

agent 有特殊的工具：
- `core_memory_append`：往 core memory 加事实
- `core_memory_replace`：替换 core memory 内容
- `archival_memory_insert`：往归档层存
- `archival_memory_search`：检索归档层

agent 用这些工具**主动管理自己的记忆**。

### 例子

```
用户："我叫小明，我是 Python 工程师"
  ↓
agent 决定这值得记 → core_memory_append("用户叫小明，Python 工程师")
  ↓
下次对话，core memory 里直接有这条，agent 不用检索就"记得"
```

---

## 3.4 ★ 上下文管理 vs 记忆存储（关键区分）

这是本系列最重要的概念区分之一。

### MemGPT/Letta 做的是「上下文管理」

让 agent **意识到上下文有限并主动管理**（像 OS 管内存）：
- agent 自己决定什么进 core memory、什么进归档
- agent 自己检索归档
- agent 自己编辑 core memory

**特征**：agent 是主动的管理者，记忆是它「操作」的对象。

### Mem0 做的是「记忆存储/检索层」

抽取、存储、检索，但**不主动管理上下文**：
- 系统从对话抽取事实
- 存到向量库
- 查询时返回

**特征**：系统是管理者，agent 是被动的消费者。

### 这是两种完全不同的思路

| 方面 | MemGPT/Letta（上下文管理） | Mem0（记忆存储） |
|---|---|---|
| 谁管理记忆 | agent 自己 | 系统 |
| agent 角色 | 主动管理者 | 被动消费者 |
| 复杂度 | 高（agent 要学怎么管） | 低（系统全自动） |
| 智能 | 高（agent 按需调度） | 低（系统机械抽取） |
| 学习曲线 | 陡 | 平缓 |

---

## 3.5 和 Self-Agent 的对照

Self-Agent 的「短期/长期」记忆可以对照：

| Self-Agent | MemGPT 对应 |
|---|---|
| 短期（checkpointer 的 messages） | 主上下文的「最近对话」 |
| 长期（Store 语义检索） | 归档层 |
| 系统提示注入记忆 | core memory |

### 关键区别

**Self-Agent 不做 agent 自编辑**：
- 记忆注入由系统（`_build_system_prompt_with_context`）自动做——系统检索 top-3 注入
- agent 不能主动「想起」某件事
- agent 不能修改自己的 core memory

**MemGPT 让 agent 自己管**：
- agent 用工具主动检索/编辑记忆
- agent 决定什么重要要记住

### Self-Agent 选「系统自动」的原因

- 简单：不用教 agent 怎么管理记忆
- 可靠：系统机械检索，不依赖 agent 的管理能力
- 通用：所有 agent 都能用，不用学

代价：agent 不能主动「想起」相关记忆——如果系统检索的 top-3 不是 agent 真正需要的，agent 没办法主动找。

---

## 3.6 MemGPT 的优势与代价

### 优势

- **agent 主动管理**：比系统机械检索更智能，agent 知道自己需要什么
- **自编辑**：重要事实写进 core memory，不用每次检索
- **虚拟内存式扩展**：突破上下文窗口限制，agent 能「记住」远超窗口的内容

### 代价

- **学习曲线陡**：agent 要学会用记忆管理工具，需要专门训练/提示
- **依赖 agent 能力**：agent 不够聪明时，记忆管理会乱（忘了存、存错地方）
- **复杂**：core memory + 归档层 + 调度逻辑，实现复杂

---

## 3.7 为什么 MemGPT 没成主流

MemGPT 思想超前，但没成主流，原因：

1. **LLM 还不够聪明**：让现在的 LLM 自己管记忆，效果不稳定
2. **系统自动方案够用**：对大多数场景，系统机械检索（Self-Agent/Mem0 模式）已经够好
3. **复杂度门槛**：core memory + 归档 + 调度，比简单向量检索复杂得多

**但它的思想有价值**——未来 LLM 更强时，「agent 自管记忆」可能是方向。

---

## 3.8 给 Self-Agent 的启示

### 启示①：agent 自管记忆作为可选模式

Self-Agent 当前是「系统自动注入」。可借鉴 MemGPT，作为**可选模式**：让 agent 用工具主动检索/编辑长期记忆。适合需要精细记忆管理的场景。

### 启示②：core memory 的「重要事实常驻」设计

MemGPT 的 core memory 让重要事实常驻上下文。Self-Agent 的系统提示每轮重拼，没有「常驻核心事实」的概念。可考虑加一个「core memory」区域，存 agent 自己标记的重要事实。

### 启示③：虚拟内存式扩展

Self-Agent 用上下文压缩（全书第 3 章）处理超长。MemGPT 的「换出到归档 + 按需换入」是另一种思路——更智能但更复杂。两者可结合。

---

## 3.9 事实声明

- 论文：Packer et al. 2023（MemGPT）
- 产品化：Letta（前名 MemGPT）
- 虚拟内存、core memory、自编辑：来自论文 + Letta 官方博客
- 「没成主流」的分析：基于实际采用的观察

→ [下一章：Mem0](04-Mem0.md)
