# 第 4 章：Cline —— Plan/Act 双模式 + MCP

> 开源自主编码 agent，VS Code 扩展（也有 SDK/CLI）。模型无关。
> 2025 GitHub Octoverse 报告称其为**贡献者增长最快的 AI 开源项目，同比增长 4704%**。

---

## 4.1 它是什么

开源自主编码 agent。形态是 VS Code 扩展（也有 SDK/CLI）。模型无关——Claude/GPT/Gemini/Ollama 都行。

地址 github.com/cline/cline，~58-65k star（调研时点，会变，建议实时核对）。2025 年是 GitHub 贡献者增长最快的 AI 开源项目。

---

## 4.2 ★ Plan / Act 双模式（核心特色）

Cline 最有辨识度的设计：**把「想」和「做」分开**。

### Plan 模式

只规划，不动手。agent 分析任务、列出步骤、和用户确认方案：

```
用户：把 UserService 重构成仓储模式
  ↓ Plan 模式
Cline 分析：
  1. 创建 UserRepository 接口
  2. 把 UserService 里的 DB 访问抽到 Repository
  3. 更新所有调用方
  4. 跑测试验证
要不要按这个方案做？
```

用户能在这个阶段纠偏（「你这个方案漏了缓存层」），**避免 agent 一头扎进去改错**。

### Act 模式

才执行。按确认的方案动手。

### 为什么这么分

1. **Plan 阶段纠偏成本低**：改几行文字 vs 改了一堆代码再发现错了
2. **Act 阶段有明确目标**：减少盲目试错
3. **降低 token 消耗和不可逆操作风险**：规划清楚了才动手

### 对比 Self-Agent

| 方面 | Self-Agent | Cline |
|---|---|---|
| 计划方式 | update_plan 工具，在 ReAct 循环里**边想边做边更新** | Plan/Act **彻底分离**，先想清楚再动手 |
| 纠偏时机 | 每个写/执行操作前审批 | Plan 阶段一次性确认方案 |

**各有取舍**：
- Self-Agent 更动态（计划可随执行调整）
- Cline 更可控（方案先过一遍）

Self-Agent 的「已知限制」是「仍是单层 ReAct」。Cline 的 Plan/Act 是一种升级方向——可以作为可选模式：长任务先 Plan 再 Act，简单任务直接 ReAct。

---

## 4.3 human-in-the-loop 审批

每步可审批，也支持 auto-approve（autopilot 模式）。

这比 Claude Code 的「93% 同意率」问题更灵活——用户可以选择「这个项目我信任，autopilot」「这个项目谨慎，逐步审批」。Self-Agent 的四档策略（gated/auto/strict/readonly）也是类似思路。

---

## 4.4 ★ MCP 一等公民

Cline 原生集成 **Model Context Protocol**。Cline 是 MCP 生态的重要推动者——很多 MCP server 是为 Cline 写的。

### 这意味着什么

Cline 不靠自己的工具生态，而是靠 **MCP 这个开放协议**接入生态。任何 MCP server 都能给 Cline 用，Cline 用户写的 MCP server 也能给别的 MCP client 用。

**对比**：
- Claude Code：内置工具为主，MCP 为辅
- Cline：MCP 为一等公民，生态靠协议而非自家工具
- Self-Agent：内置工具 + MCP + Skill 三合一（全书第 10 章）

Cline 的「MCP 优先」让它成为 MCP 生态的中心节点——这也是它增长快的原因之一（社区围绕它建了大量 MCP server）。

---

## 4.5 ★ 可 headless 跑 CI

Cline 能塞进 **GitHub Actions / GitLab 流水线**，headless 运行。

这是 Cline 区别于「只能本地用」的编码 agent 的关键。CI 集成让 Cline 能用于：
- 自动修 PR review 的小问题
- 自动跑 lint 并修
- 自动写测试

**对比 Self-Agent**：Self-Agent 的 CLI 本地模式目前主要是交互式，headless CI 是可借鉴方向（详见第 7 章）。

---

## 4.6 Cline 给我们的启示

1. **Plan/Act 分离**：作为可选模式，长任务先规划再执行，减少盲目试错
2. **MCP 一等公民**：靠协议而非自家工具建生态
3. **headless CI**：让 agent 能跑在流水线里，不只本地
4. **灵活审批**：autopilot vs 逐步审批可选，比单一策略更实用

---

## 4.7 事实声明

- star ~58-65k（2025 调研时点，Octoverse 报告称贡献者增长最快 4704%）
- Plan/Act、MCP、headless CI：来自 Cline 官方博客 + repo

→ [下一章：Cursor](05-Cursor.md)
