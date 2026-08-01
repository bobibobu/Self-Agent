"""
Skill 注册器与装饰器
--------------------
- @skill(...) 装饰器：声明式地把一个类注册为 Skill
- SkillRegistry：管理所有已注册 Skill，支持按名查找、加载/卸载
- 把 Skill 的工具合并进 Agent 工具注册表

工作流：
    @skill(name="x", description="y")   # 声明
    class XSkill(SkillBase): ...

    # 启动时：
    registry.load_all()                 # 加载所有 enabled_by_default 的 Skill
    # 它们的工具自动进入 Agent 工具集
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.skills.base import SkillBase, SkillMeta

logger = get_logger(__name__)


class SkillRegistry:
    """Skill 注册表：管理 Skill 的注册、加载、卸载。"""

    def __init__(self) -> None:
        # name → SkillBase 实例
        self._skills: dict[str, SkillBase] = {}
        # name → 是否已加载（loaded 表示工具已注入 Agent）
        self._loaded: set[str] = set()

    # ---------- 注册 ----------
    def register(self, skill_cls: type[SkillBase], meta: SkillMeta) -> SkillBase:
        """实例化并注册一个 Skill。返回实例。"""
        instance = skill_cls()
        instance.meta = meta
        if meta.name in self._skills:
            logger.warning("Skill '%s' 已存在，将被覆盖", meta.name)
        self._skills[meta.name] = instance
        logger.debug("已注册 Skill: %s（工具: %s）", meta.name, instance.tool_names)
        return instance

    # ---------- 加载/卸载 ----------
    def load(self, name: str, tool_registry: Any = None) -> bool:
        """加载指定 Skill：调用 on_load，并把其工具注入 Agent 工具注册表。

        tool_registry: app.agent.registry 模块（避免循环导入，运行时传入）
        """
        skill = self._skills.get(name)
        if skill is None:
            logger.warning("Skill '%s' 未注册", name)
            return False
        if name in self._loaded:
            logger.debug("Skill '%s' 已加载，跳过", name)
            return True

        try:
            skill.on_load()
        except Exception as e:  # noqa: BLE001
            logger.warning("Skill '%s' on_load 失败：%s", name, e)

        if tool_registry and skill.tools:
            added = tool_registry.register_tools(skill.tools)
            logger.info("Skill '%s' 已加载，注入 %d 个工具", name, added)

        self._loaded.add(name)
        return True

    def unload(self, name: str) -> bool:
        """卸载 Skill（调用 on_unload）。注：工具从 Agent 注销需额外实现，此处仅语义卸载。"""
        skill = self._skills.get(name)
        if skill is None or name not in self._loaded:
            return False
        try:
            skill.on_unload()
        except Exception as e:  # noqa: BLE001
            logger.warning("Skill '%s' on_unload 失败：%s", name, e)
        self._loaded.discard(name)
        logger.info("Skill '%s' 已卸载", name)
        return True

    def load_all_defaults(self, tool_registry: Any = None) -> int:
        """加载所有 enabled_by_default 的 Skill。返回加载数量。"""
        count = 0
        for name, skill in self._skills.items():
            if skill.meta and skill.meta.enabled_by_default:
                if self.load(name, tool_registry):
                    count += 1
        if count:
            logger.info("默认加载了 %d 个 Skill", count)
        return count

    # ---------- 查询 ----------
    def list_skills(self) -> list[dict[str, Any]]:
        """列出所有 Skill 的描述。"""
        return [s.describe() for s in self._skills.values()]

    def get(self, name: str) -> SkillBase | None:
        return self._skills.get(name)

    @property
    def loaded_names(self) -> list[str]:
        return sorted(self._loaded)


# 全局单例
skill_registry = SkillRegistry()


def skill(
    name: str,
    description: str,
    *,
    version: str = "0.1.0",
    tags: list[str] | None = None,
    author: str = "",
    enabled_by_default: bool = True,
    registry: SkillRegistry | None = None,
):
    """声明式注册 Skill 的类装饰器。

    用法：
        @skill(name="email", description="邮件助手", tags=["productivity"])
        class EmailSkill(SkillBase):
            tools = [...]
            prompt = "..."
    """
    reg = registry or skill_registry
    meta = SkillMeta(
        name=name,
        description=description,
        version=version,
        tags=tags or [],
        author=author,
        enabled_by_default=enabled_by_default,
    )

    def decorator(cls: type[SkillBase]) -> type[SkillBase]:
        reg.register(cls, meta)
        return cls

    return decorator
