"""
用户画像服务
------------
封装 Neo4j 的用户画像操作：兴趣/偏好/属性的增查。
Neo4j 不可用时用内存图（dict 兜底），保证开发期可用。
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.db.manager import db_manager

logger = get_logger(__name__)


class ProfileService:
    """用户画像服务。优先用 Neo4j，不可用则内存兜底。"""

    def __init__(self) -> None:
        self._use_neo4j: bool = False
        # 内存兜底：user_id -> {兴趣/偏好/属性}
        self._fallback: dict[str, dict[str, list[str]]] = {}

    def _ensure_neo4j(self) -> bool:
        """检查 Neo4j 是否可用。"""
        if self._use_neo4j and db_manager.neo4j is not None:
            return True
        if db_manager.neo4j is not None:
            self._use_neo4j = True
            return True
        self._use_neo4j = False
        return False

    # ---------- 写入 ----------

    async def add_interest(self, user_id: str, interest: str) -> None:
        """记录用户兴趣：(User)-[:INTERESTED_IN]->(Topic)。"""
        if self._ensure_neo4j():
            await self._neo4j_write(
                """
                MERGE (u:User {id: $user_id})
                MERGE (t:Topic {name: $interest})
                MERGE (u)-[:INTERESTED_IN]->(t)
                """,
                user_id=user_id, interest=interest,
            )
        else:
            self._fallback.setdefault(user_id, {}).setdefault("interests", []).append(interest)
        logger.info("用户画像: %s 兴趣+%s", user_id, interest)

    async def add_preference(self, user_id: str, key: str, value: str) -> None:
        """记录用户偏好：(User)-[:PREFERS {key}]->(Preference {value})。"""
        if self._ensure_neo4j():
            await self._neo4j_write(
                """
                MERGE (u:User {id: $user_id})
                MERGE (p:Preference {key: $key, value: $value})
                MERGE (u)-[:PREFERS]->(p)
                """,
                user_id=user_id, key=key, value=value,
            )
        else:
            self._fallback.setdefault(user_id, {}).setdefault(f"pref:{key}", []).append(value)
        logger.info("用户画像: %s 偏好 %s=%s", user_id, key, value)

    async def set_attribute(self, user_id: str, attr: str, value: str) -> None:
        """设置用户属性（直接挂在 User 节点上）。

        注意：Cypher 不支持参数化属性键名，必须做标识符白名单校验防注入。
        """
        # 校验 attr 为合法标识符，防止 Cypher 注入（属性键无法参数化）
        import re

        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", attr):
            raise ValueError(f"非法属性名：{attr}（仅允许字母/数字/下划线，且不以数字开头）")

        if self._ensure_neo4j():
            await self._neo4j_write(
                f"MERGE (u:User {{id: $user_id}}) SET u.`{attr}` = $value",
                user_id=user_id, value=value,
            )
        else:
            self._fallback.setdefault(user_id, {}).setdefault(f"attr:{attr}", []).append(value)
        logger.info("用户画像: %s 属性 %s=%s", user_id, attr, value)

    # ---------- 查询 ----------

    async def get_profile(self, user_id: str) -> dict[str, Any]:
        """获取用户完整画像：兴趣、偏好、属性。"""
        if self._ensure_neo4j():
            return await self._neo4j_get_profile(user_id)
        # 内存兜底
        data = self._fallback.get(user_id, {})
        return {
            "user_id": user_id,
            "interests": data.get("interests", []),
            "preferences": {k[5:]: v for k, v in data.items() if k.startswith("pref:")},
            "attributes": {k[5:]: v[-1] if v else None for k, v in data.items() if k.startswith("attr:")},
            "source": "memory_fallback",
        }

    async def get_interests(self, user_id: str) -> list[str]:
        """获取用户兴趣列表。"""
        profile = await self.get_profile(user_id)
        return profile.get("interests", [])

    # ---------- Neo4j 底层操作 ----------

    async def _neo4j_write(self, query: str, **params) -> None:
        driver = db_manager.neo4j
        async with driver.session() as session:  # type: ignore[union-attr]
            await (await session.run(query, **params)).consume()

    async def _neo4j_get_profile(self, user_id: str) -> dict[str, Any]:
        driver = db_manager.neo4j
        async with driver.session() as session:  # type: ignore[union-attr]
            # 兴趣
            result = await session.run(
                "MATCH (u:User {id:$uid})-[:INTERESTED_IN]->(t:Topic) RETURN t.name AS name",
                uid=user_id,
            )
            records = await result.value()
            interests = [r for r in records]

            # 偏好
            result = await session.run(
                "MATCH (u:User {id:$uid})-[:PREFERS]->(p:Preference) RETURN p.key AS k, p.value AS v",
                uid=user_id,
            )
            prefs: dict[str, list[str]] = {}
            async for r in result:
                prefs.setdefault(r["k"], []).append(r["v"])

            # 属性（User 节点的非 id 属性）
            result = await session.run(
                "MATCH (u:User {id:$uid}) RETURN properties(u) AS props",
                uid=user_id,
            )
            rec = await result.single()
            props = rec["props"] if rec else {}
            props.pop("id", None)

        return {
            "user_id": user_id,
            "interests": interests,
            "preferences": prefs,
            "attributes": props,
            "source": "neo4j",
        }


# 单例
_profile_service: ProfileService | None = None


def get_profile_service() -> ProfileService:
    """获取 ProfileService 单例。"""
    global _profile_service
    if _profile_service is None:
        _profile_service = ProfileService()
    return _profile_service
