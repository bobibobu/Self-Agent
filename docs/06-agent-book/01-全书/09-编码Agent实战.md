# 第 9 章：编码 Agent 实战

> 目标：把前面学的一切（ReAct、State、工具、安全）串成一个**真能在你目录里干活的编码 Agent**。
> 这章讲文件/Shell 工具、任务计划、CLI 本地模式怎么协作。

---

## 9.1 编码 Agent vs 聊天机器人

Phase 10 之前，Self-Agent 是个「能聊天并调几个玩具工具」的聊天机器人。Phase 10 之后，它有了**编码 Agent 的实质能力**：读写文件、执行命令。

这条分水岭一旦跨过，就**必须**补上安全层（第 8 章）。因为：

| 能力 | 聊天机器人 | 编码 Agent |
|---|---|---|
| 读文件 | 不能 | 能（需禁闭） |
| 改文件 | 不能 | 能（需审批） |
| 跑命令 | 不能 | 能（需沙箱） |

所以这章的内容**只有在安全层就位后才有意义**。

---

## 9.2 文件工具集

`app/agent/tools/files.py`。编码 Agent 的基本功。

### 只读类（READ 级，不审批）

| 工具 | 干什么 |
|---|---|
| `read_file(path, start_line, end_line)` | 带行号读取，支持行范围 |
| `list_dir(path)` | 列目录，跳过 .git/node_modules |
| `glob_files(pattern)` | 通配符查找 |
| `grep_files(query, file_pattern="**/*", ignore_case=True)` | 字面量内容搜索，跳过二进制和敏感文件 |

遍历类有上限（`_MAX_ENTRIES=200`、`_MAX_GREP_HITS=100`），防止在大仓库刷屏并撑爆上下文。

### 写类（WRITE 级，审批）

| 工具 | 干什么 | 安全细节 |
|---|---|---|
| `write_file(path, content)` | 覆盖写入 | 父目录自动创建 |
| `edit_file(path, old, new)` | 精确文本替换 | **匹配多处时拒绝而非猜测** |
| `delete_file(path)` | 删单个文件 | **拒绝删目录** |

**edit_file 匹配多处拒绝**是个重要设计。猜测改哪个会出错，宁可让模型看到「匹配到 N 处，请提供更精确的上下文」自己纠正。这比「自信地改错」安全得多。

### read_file 的完整实现（学习一个，其余同构）

```python
@tool
async def read_file(path: str, start_line: int = 1, end_line: int = 0) -> str:
    """读取工作区内某个文本文件的内容，带行号。"""
    ws = get_workspace()
    try:
        target = ws.resolve(path)          # ① 工作区禁闭
    except WorkspaceError as e:
        return _err(str(e))
    if ws.is_sensitive(target):            # ② 敏感文件挡一道
        return _err(f"拒绝读取敏感文件：{ws.relative(target)}")
    if not target.exists():                # ③ 存在性检查
        return _err(f"文件不存在：{path}")
    # ④ gitignore 检查、行号处理、截断 ...
    return _read_text(target, limit)
```

注意 `_err()` 统一返回字符串而不是抛异常——错误交回模型让它自己纠正，不中断 ReAct 循环。

---

## 9.3 ★ Shell 工具：全项目风险最高的工具

`app/agent/tools/shell.py`。编码 Agent 绕不开跑测试、lint、git。但这是**风险最高**的工具，所以做了很多事。

### 五道防线

```python
@tool
async def run_command(command: str, cwd: str = ".") -> str:
# 超时不走参数，来自配置 shell_timeout_seconds（默认 120s）
    """执行一条命令（不经 shell 解释器）。"""
    # 1. shlex 拆词，列表参数（防注入，第 8 章）
    # 2. _looks_destructive(argv) 挡毁灭性命令
    # 3. cwd 走 Workspace.resolve() 禁闭
    # 4. wrap_command 包沙箱（bwrap/Landlock）
    # 5. 超时杀整个进程组（只 kill 父进程会留孤儿）
    # 输出截断到 _MAX_OUTPUT_CHARS
```

### 灭绝性命令硬拒绝

```python
_DENIED = {
    "shutdown", "reboot", "halt", "poweroff", "init",
    "mkfs", "fdisk", "dd", "sudo", "su", "chown", "chmod",
}
```

`_looks_destructive(argv)` 还挡 `rm -rf 指向工作区根或更上层`。这不是完整安全边界（真正边界是沙箱），而是挡住模型最容易犯的几种致命错误。

### 进程组超时

```python
# 超时强制终止，并且杀整个进程组——只 kill 父进程会留下孤儿子进程
```

为什么杀进程组？因为命令可能 spawn 子进程（如 `pytest` 起一堆 worker）。只 kill 父进程，子进程变孤儿继续跑，超时形同虚设。

---

## 9.4 ★ 任务计划（Plan）：长任务的外部记事板

`app/agent/plan.py`。这是解决「单层 ReAct 扛不住长任务」的关键。

### 问题：ReAct 的失忆症

单层 ReAct 循环在「重构这个模块」这类任务上会失败：模型走到第七八步就**忘记最初要做什么**，或反复做同一件事直到撞 recursion_limit。

### 解决：外部记事板

不是加更多提示词，而是给它一块**外部记事板**——把计划写下来、随进展更新状态。每轮的上下文里都有一份「全局要做什么 / 现在做到哪 / 还剩什么」，**不依赖模型自己记住**。

```
╭─ 任务计划 1/3 ─╮
│ ✔ 读懂 main.py │
│ ▶ 添加注释     │
│ ○ 验证结果     │
╰────────────────╯
```

### update_plan 工具

```python
@tool
async def update_plan(steps: list[dict]) -> StateUpdate:
    """创建或更新任务计划。多步骤任务必须先用它列出计划。"""
    normalized, err = normalize(steps)
    if err:
        return StateUpdate(text=f"计划未更新：{err}")
    return StateUpdate(text=render(normalized), updates={"plan": normalized})
```

模型用它列计划、随进展更新。每完成一步再调一次，把该步标 completed、下一步标 in_progress。

### ★ 两个关键设计

**1. 计划存在 State 里**（不是提示词），随 checkpointer 持久化。所以中断、续跑、换进程之后都还在。

**2. 同一时刻只允许一个 in_progress**：

```python
running = [s for s in steps if s["status"] == "in_progress"]
if len(running) > 1:
    return [], f"同一时刻只能有一个步骤处于 in_progress，现在有 {len(running)} 个"
```

为什么？允许多个的话，模型会把所有步骤一次性标成进行中，记事板就退化成一张静态清单，起不到「现在做到哪」的作用。

### StateUpdate：工具更新状态的统一约定

```python
@dataclass
class StateUpdate:
    text: str
    updates: dict[str, Any] = field(default_factory=dict)
```

工具返回 StateUpdate 时，tools_node 认得它：用 `.text` 构造 ToolMessage（给模型看），把 `.updates` 合并进节点返回的状态增量（更新 State）。**用统一约定而不是按工具名特判**，以后再有需要改状态的工具照这个返回即可。

### 谁能看到计划

- **模型**：每轮 update_plan 返回的渲染文本（`render()`），它在 messages 里能看到
- **人**：CLI 的 `/plan` 命令、流式的 `plan_updated` 事件（让客户端渲染成常驻面板而不是滚动日志）

代码：`app/agent/plan.py:105`。

---

## 9.5 ★ CLI 本地模式：零依赖跑起来

`clients/cli/selfagent_cli/`。这是本项目最友好的入门形态。

### 双形态同内核

| 形态 | 怎么跑 | 数据存哪 | 谁用 |
|---|---|---|---|
| **本地 CLI**（默认） | `selfagent` | 单文件 SQLite | 你自己，在你的目录 |
| **远程模式** | `selfagent --remote` | 后端的四数据库 | 接服务端 |
| **服务端** | `uvicorn app.main:app` | PG+Mongo+Redis+Neo4j | 多用户，网页/HTTP |

三者**共用同一套 Agent 内核**——只是入口和存储不同。

### 为什么本地模式不要求装数据库

CLI 形态不能要求用户先装 Postgres + Mongo + Redis + Neo4j——那是服务端的形态。本地模式用 `app/memory/local_store.py` 的**单文件 SQLite**，零外部依赖：

```
~/.local/share/selfagent/projects/<工作区路径哈希>/state.db
```

`selfagent` 在任意目录敲下去就能用。

### 按项目分库

同工作区路径 → 同一个 hash → 同一个 state.db → 历史能续上。
换目录 → 新 hash → 新 state.db → 干净的新开始。

这和「工作区是编码 Agent 的上下文单位」一致。

### 本地 REPL 的核心循环

`clients/cli/selfagent_cli/localrepl.py` 的 `_drive()`：

```python
async def _drive(session, message):
    pending = await consume(stream_agent(message, session.thread_id))
    while pending is not None:  # 可能连续多次中断
        if tool in session.always_allow:
            decision = {"approved": True, "reason": "本次会话已授权"}
        else:
            choice = render_approval(pending)
            # y = 本次同意 / a = 本次会话总允许该工具 / 默认拒绝
        pending = await consume(resume_agent(session.thread_id, decision))
```

**必须把流消费完**——拿到 approval_required 不能 break（第 3、4 章解释过为什么）。

### 常用参数

```
--cwd DIR       指定工作区
--approval M    审批策略 (gated/auto/strict/readonly)
-y              跳过所有确认（仅沙箱/CI）
--remote [URL]  改用远程后端
/tools /info /trust /new /plan /help /exit
```

---

## 9.6 三种交互方式对照

| 方式 | 入口 | 流式协议 | 谁用 |
|---|---|---|---|
| **Web 聊天页** | `clients/web` (React+Vite) | SSE | 浏览器 |
| **CLI** | `selfagent` | NDJSON / 进程内 | 终端用户 |
| **API 直调** | curl | SSE / NDJSON | 集成 |

三种流式契约：
- `POST /chat`（一次性）
- `/chat/stream`（SSE，Web 端）
- `/chat/http-stream`（NDJSON，CLI/非浏览器）

---

## 9.7 外部世界怎么做

| 项目 | 编码能力特色 |
|---|---|
| **Claude Code**（闭源） | 极简 while 循环 + harness + 权限门，走向沙箱化。93% 同意率 → 沙箱替代逐次审批 |
| **Cursor**（闭源） | fork VS Code，代码库 embedding 索引，inline diff/Tab 补全/agent task |
| **Cline**（开源，~58-65k star） | **Plan/Act 双模式**（先规划再执行），MCP 一等公民，可 headless 跑 CI |
| **Aider**（开源） | **repo-map**（tree-sitter + 图排序选最相关代码），**Architect/Editor 双模型**，研究最扎实 |
| **Self-Agent**（本项目） | 工作区禁闭 + 审批 + bubblewrap/Landlock 沙箱，三层安全 |

### 值得借鉴的设计

- **Cline 的 Plan/Act 分离**：把「想」和「做」分开——Plan 模式只规划不动手，Act 模式才执行
- **Aider 的 repo-map**：tree-sitter 解析仓库，图排序选最相关代码塞进上下文——大仓库导航不爆 token。这比纯向量检索更适合代码
- **Aider 的 Architect/Editor 双模型**：Architect 只推理描述怎么改，Editor 负责落地——Plan-and-Execute 在编码场景的精致版

详见拆解①。

---

## 9.8 面试一句话

> **Q：任务计划为什么存在 State 里而不存在提示词？**
> A：因为 State 随 checkpointer 持久化，中断续跑换进程后还在。提示词每轮临时拼不持久。计划是长任务的外部记事板，每轮模型都能读到「全局要做什么、做到哪了」。

> **Q：为什么同一时刻只允许一个 in_progress？**
> A：允许多个的话，模型会把所有步骤一次性标成进行中，记事板退化成静态清单，起不到「现在做到哪」的作用。

> **Q：本地模式怎么做到零依赖？**
> A：用单文件 SQLite 做 checkpointer，按工作区路径哈希分库。不依赖任何数据库服务，selfagent 在任意目录敲下去就能用。

下一章：协议层——MCP / A2A / Skill 三种扩展机制。

→ [第 10 章：协议层](10-协议层.md)
