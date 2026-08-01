"""
Phase 3 验证脚本：长期记忆 + 用户画像 + 对话日志（无需真实 LLM key 和数据库）
=============================================================================
验证：
1. 长期记忆：add → search → 命中（用 InMemoryStore + 哈希 embedding）
2. 用户画像：add_interest/add_preference → get_profile（内存兜底）
3. 对话日志：MongoDB 不可用时静默降级，不报错
4. 集成：对话时 user_id 触发记忆/画像注入系统提示

运行：python scripts/verify_phase3.py
"""

from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    print("=" * 60)
    print("验证 1：长期记忆（add → search）")
    print("=" * 60)
    from app.memory.store import get_memory_service

    mem = await get_memory_service()
    await mem.add_memory("user1", "用户喜欢简洁的技术回答")
    await mem.add_memory("user1", "用户是 Python 开发者")
    await mem.add_memory("user1", "用户在学习 LangGraph")

    results = await mem.search_memory("user1", "用户的编程偏好", limit=3)
    print(f"  检索到 {len(results)} 条记忆:")
    for r in results:
        print(f"    - {r['content'][:40]}")
    assert len(results) > 0, "✗ 长期记忆检索为空"
    print("  ✓ 长期记忆 add/search 正常")

    print()
    print("=" * 60)
    print("验证 2：用户画像（Neo4j 不可用时内存兜底）")
    print("=" * 60)
    from app.profile.service import get_profile_service

    ps = get_profile_service()
    await ps.add_interest("user1", "人工智能")
    await ps.add_interest("user1", "系统设计")
    await ps.add_preference("user1", "回答风格", "详细")
    profile = await ps.get_profile("user1")
    print(f"  画像来源: {profile['source']}")
    print(f"  兴趣: {profile['interests']}")
    print(f"  偏好: {profile['preferences']}")
    assert "人工智能" in profile["interests"], "✗ 兴趣未记录"
    assert profile["preferences"].get("回答风格") == ["详细"], "✗ 偏好未记录"
    print("  ✓ 用户画像 add/get 正常（内存兜底）")

    print()
    print("=" * 60)
    print("验证 3：对话日志（MongoDB 不可用时静默降级）")
    print("=" * 60)
    from app.logging_service import get_conversation_logger

    logger = get_conversation_logger()
    # 不应抛异常
    await logger.log_event(
        thread_id="t1", user_id="user1", user_message="测试", agent_reply="回复",
    )
    print("  ✓ 对话日志记录不报错（MongoDB 不可用时静默）")
    history = await logger.get_history("t1")
    print(f"  历史查询: {len(history)} 条（预期 0，因 Mongo 不可用）")

    print()
    print("=" * 60)
    print("验证 4：记忆/画像注入系统提示")
    print("=" * 60)
    from app.agent.graph import _build_system_message_with_memory

    sys_msg = await _build_system_message_with_memory("编程偏好", "user1")
    assert "长期记忆" in sys_msg.content, "✗ 长期记忆未注入"
    assert "用户画像" in sys_msg.content, "✗ 用户画像未注入"
    assert "人工智能" in sys_msg.content, "✗ 兴趣未注入"
    print(f"  系统提示长度: {len(sys_msg.content)} 字符")
    print("  ✓ 长期记忆 + 用户画像 已注入系统提示")

    print()
    print("=" * 60)
    print("✅ Phase 3 全部验证通过！")
    print("  • 长期记忆（语义检索）")
    print("  • 用户画像（兴趣/偏好，内存兜底）")
    print("  • 对话日志（优雅降级）")
    print("  • 记忆与画像自动注入对话上下文")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
