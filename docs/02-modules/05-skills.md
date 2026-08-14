# Skill 系统

> Skill 是 Agent 能力的「声明式封装」：把工具 + 提示词 + 元数据打包成可插拔单元。本模块讲清楚设计动机与用法。

---

## 一、为什么需要 Skill？

工具（Tool）是原子操作。但真实场景中，能力往往是**一组工具 + 配套提示词**的组合：

> "邮件助手" = 写邮件工具 + 分类工具 + 「语气专业友好」的提示词

如果只注册一堆零散工具，LLM 面临的问题：
1. **工具表臃肿**：几十个工具堆在一起，LLM 选择成本上升、易选错
2. **提示词无法配套**：工具是「怎么做」，但「该用什么语气/策略」无处安放
3. **难以复用**：能力散落在各处，无法整体移植

Skill 解决：把相关工具和提示词**打包成一个声明式单元**，可整体加载/卸载/分享。

---

## 二、Skill 的结构

```
Skill = 元数据 + 工具集 + 提示词片段
        └──────────┴────────────┴──────────
        SkillMeta    BaseTool[]    string
```

| 组成 | 类型 | 作用 |
|---|---|---|
| 元数据 | `SkillMeta` | 名称、描述、版本、标签（自描述，可检索） |
| 工具集 | `list[BaseTool]` | 该 Skill 提供的工具（可来自 @tool 或 MCP） |
| 提示词 | `str` | 注入系统提示的能力描述（引导 LLM 用对策略） |

---

## 三、声明式用法（装饰器风格）

```python
from app.skills import skill, SkillBase

@skill(
    name="email_assistant",
    description="撰写和分类邮件",
    tags=["productivity"],
)
class EmailSkill(SkillBase):
    tools = [compose_email, classify_email]
    prompt = "你擅长邮件写作，语气专业而友好。先了解收件人再动笔。"

    def on_load(self):
        # 可选：加载时初始化（如连接邮件服务）
        ...
```

就这一段，Skill 自动注册。应用启动时 `load_all_defaults()` 会加载它，工具进入注册表，提示词注入系统提示。

---

## 四、工作流程

```
应用启动
  │
  ├─ import app.skills.builtin     # 触发 @skill 注册到 skill_registry
  │
  ├─ skill_registry.load_all_defaults()
  │     │
  │     ├─ 对每个 enabled_by_default 的 Skill：
  │     │   ├─ 调用 on_load()              # 初始化钩子
  │     │   ├─ register_tools(skill.tools) # 工具 → Agent 注册表
  │     │   └─ 标记为 loaded
  │     │
  │     └─ Skill 提示词在 _build_system_prompt() 时拼接进系统提示
  │
  └─ Agent 运行时：工具统一从 registry 取，提示词已含 Skill 指导
```

---

## 五、内置示例：math_assistant

`app/skills/builtin.py` 提供了一个完整示例：

```python
@skill(name="math_assistant", description="数学计算助手", tags=["math"])
class MathSkill(SkillBase):
    tools = [advanced_math]     # 支持 sqrt/三角函数等
    prompt = "【数学助手已激活】遇到数学问题优先用 advanced_math 精确计算..."
```

加载后：
- `advanced_math` 工具进入 Agent 工具集（与 calculator、get_weather 并列）
- 系统提示包含「数学助手已激活」片段，引导 LLM 优先用工具计算

---

## 六、Skill vs Tool vs MCP 三者关系

| 概念 | 粒度 | 关注点 |
|---|---|---|
| **Tool** | 单个原子操作 | 「怎么做」一个具体动作 |
| **MCP** | 传输协议 | 工具「怎么传递」（本地/远程/跨进程） |
| **Skill** | 能力单元 | 「组合哪些工具 + 用什么策略」（业务编排层） |

层次关系：
```
Skill（业务能力）
  ├─ Tool A（内置 @tool）
  ├─ Tool B（来自 MCP server）
  └─ 提示词（使用策略）
```

一个 Skill 的工具**可以混合来源**：既有本地 @tool，也有 MCP 远程工具。

---

## 七、如何新增一个 Skill？

1. 在 `app/skills/builtin.py`（或新建文件）定义：

```python
@skill(name="weather_pro", description="增强天气助手", tags=["weather"])
class WeatherSkill(SkillBase):
    tools = [get_weather]  # 可复用已有工具
    prompt = "查询天气时，主动补充穿衣建议和出行提示。"
```

2. 在 `app/main.py` 的 lifespan 里确保该模块被 import（触发注册）

3. 完成。启动后自动加载，工具可用，提示词注入。

---

## 八、面试要点

**Q: 为什么不直接把所有工具注册给 Agent，要套一层 Skill？**
A: 三个原因：① 工具多了 LLM 选择质量下降（context 污染），Skill 支持按场景动态加载；② 工具只有「怎么做」，缺少「使用策略」，Skill 的提示词补齐这一层；③ Skill 是自描述的（含元数据），便于管理、检索、跨项目复用。

**Q: Skill 的按需加载怎么做？**
A: 当前 `enabled_by_default` 控制是否默认加载。进阶可结合用户画像（Phase 3）：根据用户身份/场景动态 `load(name)`，实现"不同用户看到不同能力"。也可由 LLM 在路由阶段决定加载哪个 Skill（meta-agent 模式）。

**Q: Skill 和 Agent 是什么关系？**
A: Skill 是 Agent 的能力模块（has-a），不是独立 Agent。一个 Agent 可加载多个 Skill。若要让"邮件助手"成为独立可通信的 Agent，那是 A2A（Phase 4）的范畴——Skill 关注能力封装，A2A 关注 Agent 间协作。
