"""
Skill 系统
==========
Skill 是对 Agent 能力的「声明式封装」：一个 Skill = 元数据 + 工具 + 提示词片段。

为什么要 Skill？
- **能力即模块**：把"会写邮件""会查股票""会分析数据"打包成可插拔单元
- **按需加载**：根据用户/场景动态启用，避免工具表臃肿（LLM 选择成本随工具数上升）
- **复用与分享**：Skill 是自描述的，可跨项目/跨 Agent 复用

与「工具」「MCP」的关系：
- 工具（Tool）：单个原子操作（如 calculator）
- MCP：工具的「传输协议」（本地/远程、跨进程）
- Skill：能力的「组织单元」，可包含多个工具 + 专属提示词 + 元数据
  └ 一个 Skill 内部的工具可以来自 @tool，也可来自 MCP

用法（声明式注册）：
    from app.skills import skill, SkillBase

    @skill(
        name="email_assistant",
        description="撰写和分类邮件",
        tags=["productivity", "communication"],
    )
    class EmailSkill(SkillBase):
        tools = [compose_email, classify_email]
        prompt = "你擅长邮件写作，语气专业而友好。"
        def on_load(self): ...  # 可选的加载钩子
"""
