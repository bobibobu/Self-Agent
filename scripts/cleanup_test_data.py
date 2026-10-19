"""
清理测试数据污染
================
历史上 `pytest` 会直接写本机 .env 指向的真实数据库（对话日志与会话记录都是
即发即忘写入的），于是测试用的 "计算 2**10"、"北京天气怎么样？"、"hi"
会出现在真实对话历史里。tests/conftest.py 已经从根上堵住这条路，
本脚本用来清掉**已经写进去的**那批。

用法：
    python scripts/cleanup_test_data.py            # 只列出，不删（默认）
    python scripts/cleanup_test_data.py --apply    # 真的删除

只删除 thread_id 命中已知测试前缀的记录，不碰真实会话。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 测试用过的 thread_id 前缀（来自 tests/ 下各文件）
TEST_THREAD_PREFIXES = [
    "smoke-", "multi-", "stream-", "skill-",        # test_api_smoke.py
    "c-",                                           # test_client_contract.py
    "otel-", "single-call-", "acc-regression-",     # test_telemetry.py / test_regressions.py
    "raw-", "demo",                                 # 手工验证脚本
    "isolation-check",
]


def _is_test_thread(thread_id: str) -> bool:
    tid = thread_id or ""
    # 多租户模式下 thread_id 会带 "tenant:" 前缀，剥掉再比
    if ":" in tid:
        tid = tid.split(":", 1)[1]
    return any(tid.startswith(p) for p in TEST_THREAD_PREFIXES)


async def main(apply: bool) -> None:
    from app.core.config import get_settings
    from app.db.manager import db_manager

    s = get_settings()
    print(f"目标 Postgres : {s.postgres_host}:{s.postgres_port}/{s.postgres_db}")
    print(f"目标 MongoDB  : {s.mongo_host}:{s.mongo_port}/{s.mongo_db}")
    print(f"模式          : {'实际删除' if apply else '仅预览（加 --apply 才删除）'}")
    print("-" * 60)

    await db_manager.connect()

    # ---------- MongoDB：对话日志 ----------
    mongo_hits = 0
    if db_manager.mongo is not None:
        coll = db_manager.mongo["conversation_events"]
        docs = await coll.find({}, {"thread_id": 1, "user_message": 1}).to_list(length=10000)
        targets = [d for d in docs if _is_test_thread(d.get("thread_id", ""))]
        mongo_hits = len(targets)
        for d in targets[:10]:
            print(f"  [mongo] {d.get('thread_id'):<24} {str(d.get('user_message'))[:40]}")
        if mongo_hits > 10:
            print(f"  [mongo] ... 另有 {mongo_hits - 10} 条")
        if apply and targets:
            ids = [d["_id"] for d in targets]
            res = await coll.delete_many({"_id": {"$in": ids}})
            print(f"  [mongo] 已删除 {res.deleted_count} 条对话日志")
    else:
        print("  [mongo] 不可用，跳过")

    # ---------- Postgres：会话记录 ----------
    pg_hits = 0
    pool = db_manager.postgres
    if pool is not None:
        async with pool.connection() as conn:
            cur = await conn.execute("SELECT thread_id, title FROM conversations")
            rows = await cur.fetchall()
            targets = [r for r in rows if _is_test_thread(r["thread_id"])]
            pg_hits = len(targets)
            for r in targets[:10]:
                print(f"  [pg]    {r['thread_id']:<24} {r['title'] or ''}")
            if pg_hits > 10:
                print(f"  [pg]    ... 另有 {pg_hits - 10} 条")
            if apply and targets:
                cur = await conn.execute(
                    "DELETE FROM conversations WHERE thread_id = ANY(%s::text[])",
                    ([r["thread_id"] for r in targets],),
                )
                print(f"  [pg]    已删除会话记录：{cur.rowcount} 条")
    else:
        print("  [pg]    不可用，跳过")

    await db_manager.disconnect()

    print("-" * 60)
    print(f"命中：MongoDB {mongo_hits} 条对话日志，Postgres {pg_hits} 条会话记录")
    if not apply and (mongo_hits or pg_hits):
        print("加 --apply 执行实际删除。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="清理测试写入真实库的数据")
    parser.add_argument("--apply", action="store_true", help="实际删除（默认只预览）")
    args = parser.parse_args()
    from app.core.eventloop import pg_loop_factory

    # Windows 默认的 Proactor 循环跑不了 psycopg，Postgres 部分会被当成「不可用」跳过
    asyncio.run(main(args.apply), loop_factory=pg_loop_factory)
