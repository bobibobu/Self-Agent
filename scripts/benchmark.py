"""
性能基准测试：测量框架层 QPS（mock LLM，隔离 LLM 延迟）
==========================================================
目的：回答"这个 Agent 的 QPS 是多少"——先测框架本身的上限，
再结合真实 LLM 延迟做换算。

场景：
1. /health          —— 纯路由开销
2. /tools           —— 工具注册表读取
3. /chat (mock 0ms) —— 完整 Agent 链路（图执行+记忆+checkpointer），LLM 零延迟
4. /chat/stream     —— 流式路径
5. /chat (mock 500ms, 并发50) —— 模拟真实 LLM 延迟，验证并发吞吐

运行：python scripts/benchmark.py
注意：通过 ASGITransport 进程内测试（单事件循环=单 worker 等价），
     DB 未连时走内存兜底（测的是纯框架开销）。
"""

from __future__ import annotations

import asyncio
import itertools
import os
import time

# 先设置环境（在导入 app 前），关闭限流和学习，避免污染基准。
# OTEL 关掉：Jaeger 没起时导出器会反复重试，拖慢收尾还刷日志；
# 日志压到 WARNING：INFO 级的每请求日志在 300 并发下会淹没结果输出。
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["HERMES_LEARNING_ENABLED"] = "false"
os.environ.setdefault("OTEL_ENABLED", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.models import ChatRequest, ChatResponse, StreamChunk, Usage


class BenchLLM:
    """可控延迟的 mock LLM。"""

    def __init__(self, delay: float = 0.0):
        self.delay = delay

    @property
    def provider_name(self) -> str:
        return "bench"

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if self.delay:
            await asyncio.sleep(self.delay)
        return ChatResponse(
            content="基准测试回复内容",
            usage=Usage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
            model="bench", finish_reason="stop",
        )

    async def stream_chat(self, request: ChatRequest):
        if self.delay:
            await asyncio.sleep(self.delay)
        for ch in "基准测试回复内容":
            yield StreamChunk(content=ch)
        yield StreamChunk(finish_reason="stop")


def patch_llm(delay: float):
    """注入 mock LLM 到所有绑定点。"""
    import app.llm.factory as factory
    mock = lambda provider=None: BenchLLM(delay)  # noqa: E731
    factory.get_llm_client = mock
    import app.agent.nodes.agent_node as agent_node
    agent_node.get_llm_client = mock
    import app.api.routes as routes
    routes.get_llm_client = mock


async def bench(client, label, method, path, payload, n, concurrency, fresh_thread=False):
    """跑一轮基准，返回统计。

    fresh_thread=True 时每个请求用独立 thread_id——测「新会话稳态开销」；
    否则整轮共用一个 thread_id——测「长会话」：历史随请求数增长，
    checkpoint 读写和上下文管理的开销也随之上升，能看到历史增长的影响。
    """
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors = 0
    counter = itertools.count()

    async def one():
        nonlocal errors
        async with sem:
            payload_ = payload
            if fresh_thread and payload_ is not None:
                payload_ = {**payload_, "thread_id": f"fresh-{next(counter)}"}
            t0 = time.perf_counter()
            try:
                if method == "GET":
                    r = await client.get(path)
                else:
                    r = await client.post(path, json=payload_)
                if r.status_code != 200:
                    errors += 1
            except Exception:  # noqa: BLE001
                errors += 1
            latencies.append((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    await asyncio.gather(*[one() for _ in range(n)])
    duration = time.perf_counter() - t0

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.99))]
    rps = n / duration
    print(f"  {label:<38} {rps:>8.1f} rps   延迟 p50={p50:>6.1f}ms p95={p95:>6.1f}ms p99={p99:>6.1f}ms  错误={errors}")
    return rps


async def main():
    from httpx import ASGITransport, AsyncClient

    patch_llm(0.0)  # 先注入零延迟 mock
    from app.main import app

    transport = ASGITransport(app=app)

    print("=" * 100)
    print("Self-Agent 性能基准（进程内 / 单 worker 等价 / mock LLM 0ms / DB 内存兜底模式）")
    print("=" * 100)

    async with AsyncClient(transport=transport, base_url="http://bench") as client:
        # 预热（编译图、初始化单例）
        await client.post("/chat", json={"message": "warmup", "thread_id": "warm"})

        print("\n【轻量端点（并发 32）】")
        await bench(client, "GET /health ×200", "GET", "/health", None, 200, 32)
        await bench(client, "GET /tools ×200", "GET", "/tools", None, 200, 32)
        await bench(client, "GET /sessions ×200", "GET", "/sessions", None, 200, 32)

        print("\n【完整 Agent 链路（mock LLM 0ms，隔离 LLM 延迟测框架开销）】")
        await bench(client, "POST /chat ×100 并发8 (新会话)", "POST", "/chat",
                    {"message": "测试消息", "thread_id": "b0"}, 100, 8, fresh_thread=True)
        await bench(client, "POST /chat ×200 并发32 (新会话)", "POST", "/chat",
                    {"message": "测试消息", "thread_id": "b0"}, 200, 32, fresh_thread=True)
        await bench(client, "POST /chat ×300 并发64 (新会话)", "POST", "/chat",
                    {"message": "测试消息", "thread_id": "b0"}, 300, 64, fresh_thread=True)
        print("  （新会话 = 每请求独立 thread_id，历史恒为 1 轮，反映稳态框架开销）")
        await bench(client, "POST /chat ×100 并发8 (长会话)", "POST", "/chat",
                    {"message": "测试消息", "thread_id": "b1"}, 100, 8)
        print("  （长会话 = 共用 thread_id，历史随请求数增长，含上下文压缩/checkpoint 开销）")

        print("\n【流式路径（mock 0ms）】")
        await bench(client, "POST /chat/http-stream ×100 并发16", "POST", "/chat/http-stream",
                    {"message": "测试消息", "thread_id": "b4"}, 100, 16)

        # 换 500ms 延迟 mock，模拟真实 LLM（首 token 延迟）
        patch_llm(0.5)
        print("\n【模拟真实 LLM（mock 500ms）——验证框架并发能力】")
        await bench(client, "POST /chat ×100 并发50 (LLM 500ms)", "POST", "/chat",
                    {"message": "测试消息", "thread_id": "b5"}, 100, 50)

    print("\n" + "=" * 100)
    print("说明：")
    print("  · 单事件循环 = uvicorn 单 worker 等价；多 worker 线性扩")
    print("  · DB 内存兜底模式：连 Postgres 后每请求额外 +5~20ms（checkpoint 读写）")
    print("  · 真实 LLM 场景瓶颈在 provider 延迟与限流，见分析文档换算")


if __name__ == "__main__":
    asyncio.run(main())
