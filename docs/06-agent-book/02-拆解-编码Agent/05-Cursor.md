# 第 5 章：Cursor —— fork VS Code 的重 IDE 路线

> AI 优先的代码编辑器，**fork 自 VS Code**（闭源）。
> Cursor 走的是和前三家完全不同的路线：不是「agent 做成工具」，而是「IDE 做成 agent 的家」。

---

## 5.1 它是什么

AI 优先的代码编辑器，闭源。最新「Cursor 3」做成 agent 优先界面。

和 Claude Code/Aider/Cline/Self-Agent 的根本区别：那些是**命令行或扩展**，Cursor 是**完整的 IDE**。它把 AI 能力深度嵌进了编辑器的每一个角落。

---

## 5.2 ★ fork VS Code 而非做插件（核心决策）

这是 Cursor 最关键的产品决策。

### 为什么不做成 VS Code 插件

VS Code 扩展 API 有严格限制，无法：
- 深度操控 UI（inline diff 叠加、ghost text 补全）
- 操控编辑器内核（语法高亮、文件树、命令面板）
- 完整访问文件系统
- 做 agent task 的全屏体验

插件受限于扩展 API，**很多想做的体验做不出来**。

### fork 之后能做什么

fork 整个 VS Code（它是开源的，MIT），改它的源码：
- **inline diff 叠加**：AI 修改直接在原代码上叠加显示，接受/拒绝
- **Tab 深度补全**：不只是补全当前行，能预测下一步编辑
- **agent 集成**：agent task 能操控整个编辑器（开文件、跳转、运行）
- **代码库索引**：扫描整个仓库建索引

### 代价

- **维护成本巨大**：每次 VS Code 更新要 merge
- **闭源争议**：fork 开源项目做闭源产品，社区有批评
- **无法享受 VS Code 插件生态的更新**（虽然能兼容旧插件）

### 产品形态的哲学选择

Cursor 的 fork 决策揭示了一个根本问题：**是把 agent 做进 IDE（插件路线），还是把 IDE 做成 agent 的工具（fork 路线）？**

| 路线 | 代表 | 优势 | 劣势 |
|---|---|---|---|
| agent 做成 IDE 插件 | Cline、Continue | 轻量、用现有 IDE | 受扩展 API 限制 |
| IDE 做成 agent 的家（fork） | Cursor | 深度集成、体验好 | 维护重、闭源争议 |
| 独立 CLI | Claude Code、Aider、Self-Agent | 不依赖 IDE、灵活 | 无 IDE 体验 |

**Self-Agent 选的是独立 CLI 路线**——灵活、协议化、不绑 IDE。

---

## 5.3 ★ 代码库索引引擎

Cursor 把**整个代码库 embedding 化**做语义检索（codebase-wide context）。

### 怎么工作

1. 扫描整个仓库
2. 每个文件/函数/embedding 成向量
3. 用户问问题时，向量检索最相关的代码
4. 把检索结果塞进 LLM 上下文

这是 RAG（检索增强生成）在代码库的应用。

### 对比 Aider 的 repo-map

| 方面 | Cursor（向量检索） | Aider（repo-map） |
|---|---|---|
| 索引方式 | embedding 向量 | tree-sitter 结构 + 图排序 |
| 适合 | 「找语义相关」的代码 | 「找引用关系相关」的代码 |
| 精度 | 语义相似但可能无关 | 引用关系明确 |

两种各有适用场景。Self-Agent 当前用向量检索（类似 Cursor），可借鉴 Aider 的 repo-map 提升代码导航精度。

---

## 5.4 自研模型 + 路由

Cursor 不只接前沿模型，还自研小模型：
- **cursor-fast** / **cursor-tab**：自研小模型，专门做代码补全（快、便宜）
- **前沿模型路由**：复杂任务路由到 Claude/GPT-4，简单任务用自研模型

这是「**模型分层**」策略——简单任务用便宜快速的模型，复杂任务用强模型，平衡成本和体验。

**对比 Self-Agent**：Self-Agent 目前用单一模型（默认 glm-4.5-flash），可借鉴 Aider 的 Architect/Editor 和 Cursor 的模型分层思路。

---

## 5.5 四种能力合一

Cursor 把四种 AI 能力融在一个 IDE 里：
- **Chat**：侧边栏对话
- **inline edit**：选中代码直接改
- **Tab 补全**：写代码时预测下一步
- **agent task**：多步任务自动执行

前三家（Claude Code/Aider/Cline）主要做 agent task，Cursor 把所有 AI 交互形态都做了。这是 fork IDE 才能做到的体验深度。

---

## 5.6 Cursor 给我们的启示

1. **产品形态是根本选择**：agent 做 IDE 插件 vs fork IDE vs 独立 CLI，各有取舍，要先想清楚定位
2. **模型分层降本**：简单任务用小模型，复杂任务用强模型
3. **代码库索引**：向量检索（Cursor）或图排序（Aider）都是大仓库导航的解法

---

## 5.7 事实声明

- fork VS Code、代码库索引、自研模型：来自 Medium「How Cursor Actually Works」+ InfoQ Cursor 3 报道
- 闭源，具体实现细节无法源码级确认

→ [下一章：四家安全对比](06-安全对比.md)
