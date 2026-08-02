# 第 7 章：和 Self-Agent 的对比与借鉴

> 把前 6 章的拆解收口：Self-Agent 在这四家里是什么位置？哪些设计值得借鉴？

---

## 7.1 Self-Agent 在四家里的位置

| 维度 | Claude Code | Aider | Cline | Cursor | **Self-Agent** |
|---|---|---|---|---|---|
| 上下文管理 | 会话级 | **repo-map（最强）** | 会话历史 | 代码库索引 | 检索+压缩 |
| 代码理解 | 隐式 | **tree-sitter+图排序** | 隐式 | 向量索引 | grep+向量 |
| 权限模型 | 权限门→沙箱化 | git 兜底 | 审批+autopilot | IDE 沙箱 | **工作区+审批+沙箱** |
| 沙箱 | 走向 OS 级 | 无 | 靠 IDE | 靠 IDE | **bubblewrap/Landlock** |
| 改代码方式 | 内置工具 | search/replace | 内置工具 | inline diff | edit_file |
| 多模型 | Claude only | 几乎任何 LLM | 多家 | 自研+前沿 | GLM/OpenAI/Anthropic |
| CI 集成 | 有 | 终端原生 | **headless CI** | — | CLI 本地 |
| 范式 | ReAct | architect 双模型 | Plan/Act | agent task | ReAct+计划 |
| 形态 | CLI | CLI | VS Code 扩展 | fork IDE | CLI+服务端 |

---

## 7.2 ★ Self-Agent 的优势（保持）

### 安全最完整（第 6 章）

Self-Agent 的三层安全（工作区禁闭 + 四档审批 + bubblewrap/Landlock 沙箱）+ shlex 防注入，是这五家里**唯一四道防线全做**的。

- Claude Code 正在向 Self-Agent 已做到的「OS 级沙箱」演进
- Aider/Cline/Cursor 都没做命令级沙箱
- Self-Agent 的四档审批策略是最灵活的

**结论**：安全是 Self-Agent 的核心竞争力，领先于这四家。

### 多协议 LLM 抽象（全书第 5 章）

Aider 也支持多模型，但 Self-Agent 的统一抽象层（LLMClient Protocol + 三家 provider）设计更系统、更工程化。

### 双形态（全书第 9 章）

本地 CLI（零依赖 SQLite）+ 服务端（四数据库）。这四家里只有 Self-Agent 同时是「本地工具」和「可部署服务」。

### 协议化扩展（全书第 10 章）

MCP + A2A + Skill 三合一。Cline 是 MCP 一等公民，但 Self-Agent 多了 A2A（agent 间协作）和 Skill（能力封装）。

---

## 7.3 ★ 值得借鉴的设计

### 借鉴①：Aider 的 repo-map（最高优先级）

**问题**：Self-Agent 用 grep/glob + 向量检索做代码导航。对代码这种强结构数据，不如 tree-sitter + 图排序精准。

**借鉴**：加一个 repo-map 模块：
1. 用 tree-sitter 解析 Python 文件，抽类/函数签名
2. 建引用图
3. 图排序选最相关定义塞进上下文

作为新工具 `repo_map(query)`，模型用它一次拿到相关代码骨架，而不是一次次 grep。

**预期收益**：大仓库导航质量显著提升，token 消耗降低。

### 借鉴②：Aider 的 search/replace 块

**问题**：Self-Agent 的 edit_file 是单点精确替换，大改动要一次次调。

**借鉴**：让 edit_file 支持多段 search/replace 块，模型一次表达多处修改。

**预期收益**：大改动效率提升，减少多轮往返。

### 借鉴③：Cline 的 Plan/Act 分离（作为可选模式）

**问题**：Self-Agent 是单层 ReAct + update_plan（边想边做）。长任务可能迷失。

**借鉴**：加一个可选的「Plan 模式」：
- `--plan` 启动时先让 agent 出完整方案，用户确认后再 Act
- 简单任务仍用 ReAct

**预期收益**：长任务可控性提升，减少盲目试错。

### 借鉴④：Aider 的 Architect/Editor 双模型

**问题**：Self-Agent 用单一模型（默认 glm-4.5-flash）。

**借鉴**：复杂任务用双模型：
- GLM-4.6（强）当 Architect 出方案
- glm-4.5-flash（快）当 Editor 落地

**预期收益**：成本降低（贵的只用于推理），质量保持。

### 借鉴⑤：Cline 的 headless CI

**问题**：Self-Agent 的 CLI 主要是交互式。

**借鉴**：让 `selfagent` 支持 headless 模式，能塞进 GitHub Actions：
```bash
selfagent --headless --auto "修复 PR #123 的 lint 错误"
```

**预期收益**：能用于 CI 自动修小问题、自动写测试。

### 借鉴⑥：Aider 的 git 作为安全网

**问题**：Self-Agent 的 checkpointer 可恢复，但编码场景 git 更适合代码回滚。

**借鉴**：编码模式下，每次 edit_file 后自动 git commit（可配）。失败 `git reset`。

**预期收益**：代码改动可原子回滚，和 checkpointer 互补。

---

## 7.4 不建议借鉴的

### 不借鉴：Cursor 的 fork IDE 路线

Self-Agent 定位是「协议化的 agent 内核 + CLI」，不是 IDE。fork VS Code 维护成本巨大，且偏离定位。

### 不借鉴：Aider 的「无审批靠 git」

Self-Agent 定位企业级，前置拦截是必须的。git 兜底只能作为补充，不能替代审批+沙箱。

---

## 7.5 借鉴优先级建议

如果要升级 Self-Agent 的编码能力，按优先级：

| 优先级 | 借鉴 | 难度 | 收益 |
|---|---|---|---|
| ★★★ | repo-map（Aider） | 中 | 代码导航质量大幅提升 |
| ★★★ | headless CI（Cline） | 低 | 开辟 CI 用途 |
| ★★ | search/replace 多段（Aider） | 低 | 大改动效率提升 |
| ★★ | Architect/Editor 双模型（Aider） | 中 | 降本保质 |
| ★ | Plan/Act 可选模式（Cline） | 中 | 长任务可控 |
| ★ | git 自动 commit（Aider） | 低 | 代码可回滚 |

---

## 7.6 这本书的核心结论

1. **编码 Agent = harness 包裹 model**：loop 简单，harness 难
2. **安全设计在演进**：从无约束 → 逐次审批 → OS 级沙箱 + 智能策略
3. **Self-Agent 安全最完整**：三层安全 + 四档审批，领先这四家
4. **上下文管理 Self-Agent 有提升空间**：Aider 的 repo-map 是最佳借鉴
5. **产品形态是根本选择**：CLI（Self-Agent）/ IDE 插件（Cline）/ fork IDE（Cursor）/ 终端原生（Aider），各有取舍

---

## 7.7 事实声明

- 所有对比基于前 6 章已声明的事实来源
- 借鉴建议是基于当前实现差距的合理推断，未实际验证收益

---

→ [回到本书目录](00-总览.md) | [回到书架](../README.md) | [下一本书：编排框架](../03-拆解-编排框架/00-总览.md)
