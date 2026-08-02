# 第 2 章：Claude Code —— 极简循环 + 沙箱化

> Anthropic 官方命令行编码 agent，闭源。是「agentic loop + 权限门 + 沙箱」的代表实现。
> 来源：Anthropic 工程博客 + VILA-Lab 逆向分析。

---

## 2.1 它是什么

Anthropic 官方命令行编码 agent。闭源，所以我们靠工程博客和第三方逆向分析理解它。

它在编码 Agent 领域的地位特殊——因为 Anthropic 同时做模型（Claude）和 harness（Claude Code），能做深度优化。

---

## 2.2 极简的 agent 循环

VILA-Lab 的逆向结论：**Claude Code 的循环本质就是一个 while 循环**：

```
读上下文 → 模型决策 → 调工具 → 观察结果 → 回到读上下文
```

没有图、没有复杂状态机。**复杂度全在循环外面**——harness 管上下文、权限、执行、恢复、审计。

### 这意味着什么

模型（Claude）只是决策点。真正的工程难点在 harness：
- **上下文管理**：决定每次给模型看什么（这是 Claude Code 的核心机密）
- **权限**：危险操作拦截
- **执行**：真的调 bash/edit/read 等工具
- **恢复**：工具失败、模型产生无效输出怎么办
- **审计**：记录所有动作供回溯

---

## 2.3 权限门与「93% 同意率」

默认对每个敏感动作（写文件、跑命令）弹审批。**逐次审批**是大多数编码 Agent 的初始设计。

但 Anthropic 公布了一个关键数据：**用户对 93% 的权限提示点了同意**。

这个数字说明「逐次审批」在效率上**失效**了：
- 用户要么无脑同意（审批形同虚设）
- 要么被频繁打断而烦死
- 真正危险的 7% 被淹没在 93% 的噪音里

---

## 2.4 ★ 沙箱替代逐次审批（关键演进）

Anthropic 官方做法（来自博客 *Making Claude Code More Secure and Autonomous*）：

> **在预定义边界内让 Claude 更自由地工作**

把「每次问」升级成「圈定一块地方随便干」。

### 为什么这是个好主意

1. **逐次审批的认知负担太重**——93% 同意率证明它失效
2. **沙箱是硬约束**——不依赖用户每次都正确判断
3. **圈定边界后 agent 可以放心试错**——反正出不去，可以激进地改+跑+改

### 演进的含义

从「应用级权限提示」→「OS 级强制隔离」。这是编码 Agent 安全设计的**集体方向**。

**对 Self-Agent 的意义**：Self-Agent 已经用 bubblewrap/Landlock 做了 OS 级沙箱（全书第 8 章），在这个方向上**超前于 Claude Code 的公开实现**。但 Self-Agent 没有放弃审批——因为沙箱内 agent 仍可能干用户不想的事（删源码），所以两者互补。

---

## 2.5 harness 包裹 model（重申第 1 章的框架）

Claude Code 是「harness 包裹 model」的典型：

| harness 零件 | Claude Code 怎么做 |
|---|---|
| 上下文管理 | 会话级（核心机密，未公开细节） |
| 权限 | 权限门 → 走向沙箱化 |
| 执行 | 内置工具（bash/edit/read/...） |
| 恢复 | 工程化处理（未公开） |
| 审计 | 记录所有动作 |

---

## 2.6 闭源的局限

因为闭源，我们对 Claude Code 的理解局限于：
- Anthropic 自己讲的（博客、文档）
- 第三方逆向（VILA-Lab、Fluid Attacks 等）
- 行为观察

具体实现细节（上下文怎么拼、失败怎么恢复、工具具体怎么定义）无法源码级确认。**这是为什么本系列把 Aider 作为「最佳研究对象」——它开源，工程研究最扎实**（第 3 章）。

---

## 2.7 Claude Code 给我们的三个启示

1. **loop 简单，harness 难**：别在循环上花太多心思，把精力放在上下文管理、权限、恢复上
2. **逐次审批会失效**：要么用沙箱替代，要么用更智能的审批策略（Self-Agent 的四档策略是一种）
3. **OS 级沙箱是正确方向**：Claude Code 正在向 Self-Agent 已经做到的方向演进

---

## 2.8 事实声明

- 循环极简、harness 包裹 model：VILA-Lab「Dive into Claude Code」逆向分析
- 93% 同意率：Anthropic 官方数据
- 沙箱化方向：Anthropic 博客「Making Claude Code More Secure and Autonomous」
- 具体实现细节因闭源无法源码级确认，相关描述基于公开资料推断

→ [下一章：Aider](03-Aider.md)
