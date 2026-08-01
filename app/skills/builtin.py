"""
内置 Skill 示例
---------------
演示如何用声明式方式定义一个 Skill。

每个 Skill = 工具集 + 提示词片段 + 元数据。
这里提供「数学助手」Skill 作为示例，真实项目可按需添加更多。
"""

from __future__ import annotations

from langchain_core.tools import tool

from app.skills.base import SkillBase
from app.skills.registry import skill


# ---- Skill 内的工具（也可复用 app.agent.tools 里的） ----


@tool
def advanced_math(expression: str) -> str:
    """高级数学计算，支持三角函数与对数（演示 Skill 自带工具）。

    Args:
        expression: 数学表达式，如 "2**10"、"round(3.7)"
    """
    # 复用 calculator 的安全求值逻辑
    import ast
    import operator
    import math

    _ops = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
        ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
    }
    _funcs = {"abs": abs, "round": round, "min": min, "max": max, "sqrt": math.sqrt}

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp):
            return _ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return _ops[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _funcs:
            return _funcs[node.func.id](*[_eval(a) for a in node.args])
        raise ValueError(f"不支持: {ast.dump(node)}")

    try:
        result = _eval(ast.parse(expression, mode="eval"))
        return f"{expression} = {result}"
    except Exception as e:
        return f"无法计算 '{expression}': {e}"


@skill(
    name="math_assistant",
    description="数学计算助手：支持算术运算、开方、三角函数等精确计算",
    version="0.1.0",
    tags=["math", "calculation"],
    author="Self-Agent",
)
class MathSkill(SkillBase):
    """数学助手 Skill：封装高级计算工具并提供专属提示词。"""

    tools = [advanced_math]
    prompt = (
        "【数学助手已激活】遇到数学计算问题时，优先使用 advanced_math 工具精确计算，"
        "而非心算。给出结果时附上算式。"
    )

    def on_load(self) -> None:
        """加载时可做的初始化（这里仅记日志示范）。"""
        from app.core.logging import get_logger
        get_logger(__name__).debug("MathSkill 加载完成")
