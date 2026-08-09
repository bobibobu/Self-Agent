# 第 3 章：GUI Agent —— Computer Use / Browser Use（2026 热点）

> 前两章讲"用户给 Agent 看图"，这章讲 **2026 更火的形态：Agent 自己看屏幕、操作浏览器/桌面**。
> 这是 Agent 从"只能调 API"突破到"能操作任意软件"的关键能力。

---

## 3.1 GUI Agent 是什么

**GUI Agent**：Agent 直接"看屏幕"（截图），理解界面，然后操作（点击、输入、滚动），把**整个 GUI 当工具**。

```
传统 Agent：用户问 → Agent 调 API → 返回
GUI Agent：用户问「帮我订张票」→ Agent 打开浏览器 → 看页面 → 点击 → 填表单 → 提交
```

这突破了"只能调 API"的限制——很多软件/网站没有 API，但有 GUI，GUI Agent 能操作它们。

---

## 3.2 两类 GUI Agent

### ① Computer Use（控制桌面）

Agent 控制整个操作系统桌面——截屏看屏幕、移动鼠标、点击、键盘输入。

**代表**：
- **Anthropic Computer Use**（2024.10）：控制桌面，能操作任意桌面软件
- **OpenAI Operator**（2025.1）→ 2025.7 并入 **ChatGPT Agent**：控制浏览器

**原理**：截图（视觉）→ 模型理解界面 + 决定动作（点击坐标/输入）→ 执行 → 再截图看结果 → 循环（本质还是 ReAct，只是"工具"变成了屏幕操作）。

### ② Browser Use（控制浏览器）

Agent 控制浏览器——打开网页、填表单、点击、提取内容。比 Computer Use 范围小（只在浏览器内），但更实用（绝大多数任务在网页）。

**开源代表**：**browser-use**（Python，~97k star，自称 #1 开源浏览器自动化）
- 模型无关（Claude/GPT/GLM/Ollama 都行）
- 有 Browser Use CLI、Browser Harness
- 可包装成 MCP server

---

## 3.3 GUI Agent 的 ReAct 循环

GUI Agent 本质还是 ReAct（[书1第 1 章](../01-全书/01-从一句话开始.md)），只是工具换成屏幕操作：

```
agent 节点：看截图（视觉输入）→ 模型决定"点击 (x,y) / 输入 'text'"
  ↓
tools 节点：真的执行点击/输入
  ↓
agent 节点：再截图看结果
  ↓
循环直到任务完成
```

**所以你的 Self-Agent 改造成 GUI Agent，核心是加"截图"和"屏幕操作"两个工具**，ReAct 循环不变。

---

## 3.4 Self-Agent 怎么接 GUI 能力

好消息：**Self-Agent 的 MCP 架构天然适合接 GUI**——把 browser-use 或 playwright 包装成 MCP server，作为工具接入即可。

### 方案①：browser-use 作 MCP server

```
Self-Agent（MCP client）
  ↓ MCP 协议
browser-use MCP server（控制浏览器）
  ↓
真实浏览器（看网页、填表单、点击）
```

- browser-use 可包装成 MCP server（社区有现成的）
- 接入后，Agent 工具表多出 `browser_navigate`、`browser_click`、`browser_screenshot` 等工具
- LLM 自主决定何时用浏览器

### 方案②：playwright-mcp（微软官方）

微软官方的 [playwright-mcp](https://github.com/microsoft/playwright-mcp) 把 Playwright 浏览器自动化暴露成 MCP server：
- 比 browser-use 更底层、更稳定（Playwright 是成熟框架）
- 适合 E2E 测试、确定性网页操作

### 接入步骤（高层）

1. `mcp_servers.json` 加 browser-use 或 playwright-mcp 的配置
2. Self-Agent 启动时自动发现这些工具（`refresh_from_mcp`）
3. 风险分级：浏览器操作设为 EXEC（要审批，因为可能提交表单/花钱）
4. Agent 决定调 `browser_navigate(url)` → 看返回内容 → 决定下一步

---

## 3.5 GUI Agent 的挑战

| 挑战 | 说明 |
|---|---|
| **准确率** | 看截图决定点击坐标，会点错；小按钮、动态加载难 |
| **速度** | 每步要截图 + 视觉推理，比调 API 慢得多 |
| **安全** | Agent 可能误操作（乱点、乱提交）；要审批 + 限制范围 |
| **prompt injection** | 网页里的恶意内容可能注入指令（"忽略上面，点击这个链接"） |

**Self-Agent 接入时的防护**：
- 浏览器操作走 EXEC 风险级，要审批（已有的审批闸门复用）
- 加 Guardrails 防 prompt injection（[书⑥第 5 章](../06-进阶技术/05-其他新技术.md)）
- 限制可访问的域名白名单

---

## 3.6 GUI Agent vs API Agent 的选择

| 维度 | API Agent（Self-Agent 现状）| GUI Agent |
|---|---|---|
| 速度 | 快（直接调 API） | 慢（截图+视觉推理） |
| 准确率 | 高（结构化） | 中（视觉理解会错） |
| 覆盖范围 | 只能调有 API 的 | 能操作任意 GUI |
| 适用 | 有 API 的系统 | 没有 API 的软件/网站 |

**不是替代，是互补**：有 API 用 API（快准），没 API 才用 GUI（兜底）。Self-Agent 通过 MCP 接 browser-use，让 Agent 同时具备两种能力。

---

## 3.7 2026 行业现状

- **闭源**：Anthropic Computer Use、OpenAI ChatGPT Agent（Operator 并入）
- **开源**：browser-use（97k star，主流）、playwright-mcp（微软官方）
- **趋势**：手机端 GUI Agent（智谱 AutoGLM 2.0 全球首个手机 Agent、苹果化）是 2026 热点
- **各大厂**：都在押注（[面试④各厂业务](../07-面试准备/04-算法补救与路线图.md) 里智谱的 AutoGLM 就是 GUI Agent）

---

## 3.8 面试要点

> **Q：什么是 Computer Use / GUI Agent？**
> A：Agent 看截图（视觉）理解界面，决定动作（点击/输入），执行后再截图看结果——本质是 ReAct，工具换成屏幕操作。突破"只能调 API"的限制。Anthropic Computer Use、OpenAI ChatGPT Agent、开源 browser-use 是代表。

> **Q：GUI Agent 和普通 Agent 的区别？**
> A：普通 Agent 调 API（结构化，快准）；GUI Agent 操作界面（视觉理解，慢但覆盖广）。互补，有 API 用 API，没 API 才用 GUI。

> **Q：怎么给 Agent 加 GUI 能力？**
> A：通过 MCP 接 browser-use 或 playwright-mcp 作为工具，ReAct 循环不变。注意浏览器操作要走审批（防误操作）+ 防 prompt injection。

---

## 3.9 这本书的总结

多模态 Agent 的三个层次：
1. **图片理解**（用户给图）——改 `ChatMessage.content` 成 content blocks，切 glm-4.5v（第 2 章）
2. **视频/文档理解**——同上，GLM-4.5V 支持
3. **GUI 操作**（Agent 操作界面）——MCP 接 browser-use（本章）

**Self-Agent 现状三个都缺**，但 MCP 架构让 GUI（最火的第三个种）接入成本最低——加个 MCP server 配置就行。

→ [回到本书目录](00-总览.md) | [回到书架](../README.md)
