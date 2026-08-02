# 第 3 章：Aider —— repo-map + Architect/Editor（工程研究范本）

> 终端原生 AI 结对编程工具，git 原生，可接几乎任何 LLM。作者 Paul Gauthier。
> **Aider 是编码 agent 里「工程研究味」最浓的**——repo-map、edit formats、Architect 模式都有论文级博客支撑。
> **也是本系列的最佳研究对象**：开源、研究扎实、代码量适中、直接对标编码能力。

---

## 3.1 它是什么

终端原生（terminal-native）的 AI 结对编程工具。特点：

- **git 原生**：每次修改自动 commit，失败可回滚（git 就是它的「撤销键」和「审计日志」）
- **模型无关**：可接几乎任何 LLM（Claude/GPT/DeepSeek/本地 Ollama）
- **工程研究最扎实**：作者写了大量技术博客，每个设计都有数据支撑（SWE-bench 基准）

地址 github.com/Aider-AI/aider，star 数待核实（估计数万）。

---

## 3.2 ★ repo-map：tree-sitter + 图排序（最值得学习）

这是 Aider 最值得学习的设计，解决了第 1 章的「难题①：大仓库怎么不爆 token」。

### 问题

大仓库动辄几十万行代码，不可能全塞进 LLM 上下文。但 agent 又需要「看到」整个仓库的结构才能导航。怎么办？

### Aider 的解法（三步）

**第 1 步：tree-sitter 解析全仓库**

用 **tree-sitter**（增量解析库）解析整个仓库的所有源文件，抽取**类/函数/签名**（不抽函数体）：

```python
# 假设仓库有 1000 个函数，repo-map 不抽函数体，只抽签名：
class UserService:
    def get_user(self, user_id: int) -> User: ...
    def create_user(self, name: str) -> User: ...

def calculate_price(items: list[Item]) -> float: ...
```

这样 1000 个函数的「骨架」可能只占几千 token，而完整代码是几十万 token。

**第 2 步：建图**

把这些定义建成一张**引用图**——谁引用谁（函数 A 调用函数 B，就有 A→B 的边）。

**第 3 步：图排序选最相关**

用**图排序算法**（类似 PageRank 的思路）算出每个定义的「重要性分数」。然后根据当前编辑的文件，选**最相关的定义子集**塞进上下文。

### 为什么用图排序而不是向量检索

这是 Aider 最深刻的洞察：**代码的「相关性」不是语义相似，而是引用关系**。

- 向量检索（RAG）找「语义相近」的代码——但代码里两个同名函数可能语义相近却毫无关系
- 图排序找「引用关系近」的代码——你改 `UserService.get_user`，它把调用 `get_user` 的地方都带出来

对代码这种**强结构数据**，tree-sitter + 图排序比纯向量检索更精准。

### 对比 Self-Agent

Self-Agent 用 grep/glob + 向量检索做代码导航。对自然语言文档，向量检索很合适；但对**代码**，Aider 的 repo-map 更精准。

**借鉴建议**：Self-Agent 可以加一个 repo-map 模块，对 Python 文件做 tree-sitter 解析 + 图排序，作为「代码导航」工具。这比让模型一次次 grep 更高效。

---

## 3.3 ★ 结构化 edit formats

Aider 让 LLM 用 **search/replace 块**表达修改，而不是直接输出整个文件：

```
<<<<<<< SEARCH
def old_func():
    pass
=======
def new_func():
    return 42
>>>>>>> REPLACE
```

### 为什么不用「输出整个文件」

- **大文件浪费 token**：改一行输出一万行
- **容易引入意外修改**：模型重写整个文件时，可能在无关地方「顺手」改动
- **难以审查**：diff 一眼看出改了啥，整个文件要对比

### 多格式自适应

Aider 按模型能力自动选格式：
- 强模型（Claude/GPT-4）：用 **diff** 或 **udiff**（更紧凑）
- 弱模型：用 **search/replace**（更容错）
- 最差模型：用 **whole file**（最简单但最浪费）

### 对比 Self-Agent

Self-Agent 的 `edit_file` 也是精确替换（old → new），思路一致。但 Aider 的多格式自适应是更成熟的设计——根据模型能力动态选格式，平衡 token 效率和容错。

---

## 3.4 ★ Architect / Editor 双模型模式（SOTA）

这是 **Plan-and-Execute 在编码场景的精致版**，在 SWE-bench 风格基准上刷新了 SOTA。

### 分工

- **Architect 模型**（强推理，如 Claude/GPT-4）：**只做推理**，描述「应该怎么改」——用自然语言说清楚改动方案，但不直接产出代码
- **Editor 模型**（擅长落地，如 deepseek-coder）：**负责落地**，把 Architect 的描述变成实际的 search/replace 块

### 为什么这么分

推理和落地是**两种能力**：
- 推理：理解问题、设计方案——强模型擅长，但贵且慢
- 落地：把方案转成精确的代码编辑——专精代码的小模型擅长，且快且便宜

分工让「**贵模型想、便宜模型干**」，兼顾质量和成本。

### 解决第 1 章的「难题③：长任务不迷失」

Architect 先把整个改动方案想清楚（plan），Editor 按方案执行（execute）。这就是 Plan-and-Execute 在编码场景的应用——比 Self-Agent 的「边想边做边更新计划」更彻底。

### 对比 Self-Agent

Self-Agent 是单层 ReAct + update_plan（边想边做）。**已知限制**：无子 Agent / 并行分解。如果要升级，Aider 的 Architect/Editor 双模型是参考方向：
- 用 GLM-4.6（强）当 Architect 出方案
- 用 glm-4.5-flash（快）当 Editor 落地
- 成本降低，质量保持

---

## 3.5 三种 chat 模式

- **ask**：只问问题不改代码
- **code**：直接改代码（单模型）
- **architect**：Architect+Editor 双模型

---

## 3.6 git 作为安全网

Aider 每次修改自动 commit。这意味着：
- **失败可回滚**：`git reset` 就能撤销
- **审计**：git log 就是完整的修改历史
- **diff 友好**：每次 commit 是原子改动

这把 git 当成了「兜底安全层」——即使模型改错了，git 能救回来。这和 Self-Agent 的「审批+沙箱」是两种思路：Aider 信任 git 的可回滚性，Self-Agent 不信任模型要先拦。

---

## 3.7 Aider 给我们的启示

1. **repo-map 是代码导航的最优解**：tree-sitter + 图排序，比向量检索更适合代码
2. **结构化 edit formats**：让模型用 search/replace 表达修改，比输出整个文件高效
3. **Architect/Editor 双模型**：推理和落地分工，是 Plan-and-Execute 在编码场景的精致版
4. **git 作为安全网**：可回滚性也是一种安全设计

Aider 是编码 Agent 里**工程研究最扎实的**，每个设计都有数据和基准支撑。如果你想深入研究编码 Agent，Aider 的博客（aider.chat）是必读。

---

## 3.8 事实声明

- repo-map：aider.chat/2023/10/22/repomap.html
- Architect 模式：aider.chat/2024/09/26/architect.html（SWE-bench SOTA）
- edit formats：aider.chat/docs/more/edit-formats.html
- star 数待核实（估计数万）

→ [下一章：Cline](04-Cline.md)
