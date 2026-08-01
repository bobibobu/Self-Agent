"""
用量统计服务
-----------
从 MongoDB 聚合 token 用量与成本估算，按 用户/时间/provider 维度。

依赖对话日志（conversation_events 集合）记录的 usage 字段。
成本按内置价格表估算（GLM-4.5-flash 免费，其他按公开定价）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.logging import get_logger
from app.db.manager import db_manager

logger = get_logger(__name__)

# 内置价格表（美元/百万 token），用于成本估算。None = 免费
_PRICE_TABLE: dict[str, dict[str, float | None]] = {
    "glm-4.5-flash": {"input": 0.0, "output": 0.0},
    "glm-4.6": {"input": 0.6, "output": 2.2},
    "glm-4.5": {"input": 0.6, "output": 2.2},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "claude-3-5-haiku-latest": {"input": 0.8, "output": 4.0},
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """估算单次调用成本（美元）。"""
    price = _PRICE_TABLE.get(model, {"input": 1.0, "output": 3.0})  # 未知模型用保守默认
    in_cost = (prompt_tokens / 1_000_000) * (price["input"] or 0)
    out_cost = (completion_tokens / 1_000_000) * (price["output"] or 0)
    return round(in_cost + out_cost, 6)


class StatsService:
    """用量统计。"""

    async def get_usage_stats(self, *, user_id: str | None = None, days: int = 7) -> dict[str, Any]:
        """获取用量统计（token 数、成本、请求数、按天分布）。

        Args:
            user_id: 按用户过滤（None 则全部）
            days: 统计最近多少天
        """
        if db_manager.mongo is None:
            return {"error": "MongoDB 不可用"}

        since = datetime.now(timezone.utc) - timedelta(days=days)
        match: dict[str, Any] = {"ts": {"$gte": since}}
        if user_id:
            match["user_id"] = user_id

        try:
            # 聚合管道
            pipeline = [
                {"$match": match},
                {"$group": {
                    "_id": None,
                    "total_requests": {"$sum": 1},
                    "total_prompt": {"$sum": "$usage.prompt_tokens"},
                    "total_completion": {"$sum": "$usage.completion_tokens"},
                    "total_tokens": {"$sum": "$usage.total_tokens"},
                    "errors": {"$sum": {"$cond": [{"$ifNull": ["$error", False]}, 1, 0]}},
                    "models": {"$addToSet": "$provider"},
                }},
            ]
            cursor = db_manager.mongo["conversation_events"].aggregate(pipeline)
            docs = await cursor.to_list(length=1)
            agg = docs[0] if docs else {}

            # 按天分布
            daily_pipeline = [
                {"$match": match},
                {"$group": {
                    "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$ts"}},
                    "requests": {"$sum": 1},
                    "tokens": {"$sum": "$usage.total_tokens"},
                }},
                {"$sort": {"_id": 1}},
            ]
            daily_cursor = db_manager.mongo["conversation_events"].aggregate(daily_pipeline)
            daily = await daily_cursor.to_list(length=days + 1)

            # 成本估算
            total_prompt = agg.get("total_prompt") or 0
            total_completion = agg.get("total_completion") or 0
            # 用平均模型估（简化；精确应按每次调用的 model 分别算）
            models = agg.get("models") or []
            avg_model = models[0] if models else "glm-4.5-flash"
            cost = estimate_cost(avg_model, total_prompt, total_completion)

            return {
                "period_days": days,
                "total_requests": agg.get("total_requests", 0),
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_tokens": agg.get("total_tokens", 0),
                "estimated_cost_usd": cost,
                "error_count": agg.get("errors", 0),
                "models_used": models,
                "daily": [{"date": d["_id"], "requests": d["requests"], "tokens": d["tokens"]} for d in daily],
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("统计聚合失败：%s", e)
            return {"error": str(e)}


_stats_service: StatsService | None = None


def get_stats_service() -> StatsService:
    global _stats_service
    if _stats_service is None:
        _stats_service = StatsService()
    return _stats_service
