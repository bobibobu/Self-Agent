"""
Skill 基类与数据模型
--------------------
定义 Skill 的核心结构与生命周期钩子。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


class SkillMeta(BaseModel):
    """Skill 的元数据（自描述，用于展示与检索）。"""

    name: str                                   # 唯一标识（snake_case）
    description: str                            # 一句话描述
    version: str = "0.1.0"
    tags: list[str] = Field(default_factory=list)
    author: str = ""
    enabled_by_default: bool = True             # 是否默认启用


class SkillBase:
    """Skill 基类。子类通过类属性声明工具与提示词。

    子类约定覆写：
        tools: list[BaseTool]    该 Skill 提供的工具
        prompt: str              注入系统提示词的能力描述片段（可空）

    可选钩子：
        on_load(self)            Skill 被加载时调用（可做初始化，如建连接）
        on_unload(self)          Skill 被卸载时调用（清理资源）
    """

    # 元数据（子类用 @skill 装饰器注入，或直接定义 Meta 内嵌类）
    meta: SkillMeta | None = None

    tools: list[BaseTool] = []
    prompt: str = ""

    def on_load(self) -> None:
        """加载钩子（可选）。"""
        pass

    def on_unload(self) -> None:
        """卸载钩子（可选）。"""
        pass

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]

    def describe(self) -> dict[str, Any]:
        """返回该 Skill 的可序列化描述。"""
        m = self.meta or SkillMeta(name="", description="")
        return {
            "name": m.name,
            "description": m.description,
            "version": m.version,
            "tags": m.tags,
            "enabled_by_default": m.enabled_by_default,
            "tools": self.tool_names,
            "has_prompt": bool(self.prompt),
        }
