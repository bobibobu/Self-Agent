"""
内置工具集
----------
用 langchain_core 的 @tool 装饰器定义工具，
工具的 docstring + 类型注解会自动转成给 LLM 的 function schema。

LLM 看到 schema → 决定调用哪个工具、传什么参数 →
Agent 框架执行工具 → 把结果回填给 LLM。

这里提供通用个人助理场景的示例工具：
- calculator：数学计算（安全的表达式求值）
- get_current_time：获取当前时间
- get_weather：模拟天气查询（演示用，可替换成真实 API）
"""

from __future__ import annotations

import ast
import operator
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------- 安全的表达式求值 ----------
# 只允许数字、运算符、括号、部分函数，禁止任意属性访问/调用
_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
_SAFE_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
}


def _safe_eval_node(node):
    """递归求值 AST 节点，遇到不允许的结构就抛错。"""
    if isinstance(node, ast.Expression):
        return _safe_eval_node(node.body)
    if isinstance(node, ast.Constant):  # 数字
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("不支持的常量")
    if isinstance(node, ast.BinOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
        return op(_safe_eval_node(node.left), _safe_eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        op = _SAFE_OPS.get(type(node.op))
        if op is None:
            raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")
        return op(_safe_eval_node(node.operand))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCS:
            raise ValueError("不允许的函数调用")
        args = [_safe_eval_node(a) for a in node.args]
        return _SAFE_FUNCS[node.func.id](*args)
    raise ValueError(f"不支持的表达式: {ast.dump(node)}")


# ==================== 工具定义 ====================


@tool
def calculator(expression: str) -> str:
    """对数学表达式求值，支持 + - * / % ** // 与 abs/round/min/max。

    Args:
        expression: 数学表达式，例如 "3 + 4 * 2" 或 "round(3.14159, 2)"
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval_node(tree)
        logger.info("calculator: %s = %s", expression, result)
        return f"{expression} = {result}"
    except Exception as e:
        return f"无法计算 '{expression}'：{e}"


@tool
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """获取指定时区的当前时间。

    Args:
        timezone: IANA 时区名，例如 "Asia/Shanghai"、"UTC"、"America/New_York"。默认上海。
    """
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        return f"未知时区：{timezone}，请使用 IANA 时区名，如 Asia/Shanghai"
    now = datetime.now(tz)
    formatted = now.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    return f"{timezone} 当前时间：{formatted}"


@tool
def get_weather(city: str) -> str:
    """查询指定城市的天气（演示用，返回模拟数据）。

    本工具有意保留为模拟实现，用于演示 Agent 的工具调用闭环。
    真实场景可通过 MCP 接入和风天气/OpenWeather 等真实服务（见 mcp_servers.json.example）。

    Args:
        city: 城市名，例如 "北京"、"上海"
    """
    # 演示：返回模拟数据。可通过 MCP 接入真实天气服务。
    mock = {
        "北京": ("晴", "26°C", "湿度 40%", "北风 3 级"),
        "上海": ("多云", "29°C", "湿度 65%", "东南风 2 级"),
        "广州": ("雷阵雨", "31°C", "湿度 80%", "南风 2 级"),
    }
    if city in mock:
        cond, temp, hum, wind = mock[city]
        return f"{city}：{cond}，气温 {temp}，{hum}，{wind}"
    return f"{city}：晴转多云，气温 25°C，湿度 50%，微风（模拟数据）"


# 暴露给 graph 注册的工具列表
ALL_TOOLS = [calculator, get_current_time, get_weather]

# 工具名 → 工具函数 的映射，供 tools 执行节点查找
TOOL_MAP = {t.name: t for t in ALL_TOOLS}

# 内置工具的风险等级。三者都是纯计算/查询，不碰文件也不执行命令，
# 归为只读，不该为它们弹审批。
# 显式写在这里而不是靠 @tool 的参数：不同 langchain-core 版本的
# 装饰器签名不一致（有的叫 metadata，有的叫 extras）。
TOOL_RISKS = {
    "calculator": "read",
    "get_current_time": "read",
    "get_weather": "read",
}
