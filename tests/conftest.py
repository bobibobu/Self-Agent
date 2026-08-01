"""
测试隔离
========
**测试绝不能写开发者的真实数据库。**

背景：应用的对话日志（Mongo）和会话记录（Postgres）都是即发即忘写入的
（app/agent/graph.py 的 _log_conversation / _touch_session）。
在本机 .env 指向真实库的情况下直接 `pytest`，测试里那些
"计算 2**10"、"北京天气怎么样？"、"hi" 会全部落进真实的对话历史和会话列表，
用户打开 Web 端就会看到一堆自己没问过的问题。

这里在**任何 app 模块被导入之前**把所有数据库指向黑洞端口，
从根上断掉写入路径。conftest.py 由 pytest 最先导入，时机是对的。

副作用是测试也快了：原先每次跑都要在四个数据库的连接超时上耗掉几十秒。
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# 必须在 import app.* 之前执行——get_settings() 带 lru_cache，读一次就定型了
# ---------------------------------------------------------------------------
_BLACKHOLE = {
    # 端口 1 上不会有服务，连接立刻被拒（比不可解析的主机名快，也比超时快）
    "POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "1",
    "MONGO_HOST": "127.0.0.1", "MONGO_PORT": "1",
    "REDIS_HOST": "127.0.0.1", "REDIS_PORT": "1",
    "NEO4J_URI": "bolt://127.0.0.1:1",
    # 认证与限流：测试默认走匿名，需要认证的用例自己开
    "AUTH_ENABLED": "false",
    "RATE_LIMIT_ENABLED": "false",
    "MULTI_TENANT_ENABLED": "false",
    # 追踪默认关，需要的用例自己装 exporter
    "OTEL_ENABLED": "false",
    "OTEL_CAPTURE_CONTENT": "false",
    # 别去连真实 LLM
    "GLM_API_KEY": "", "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "",
    "EMBEDDING_PROVIDER": "none",
    # 工具审批默认放行：绝大多数用例测的是执行机制而不是审批策略，
    # 每个用例都去理会审批只会制造噪音。审批策略本身由
    # tests/test_coding_tools.py::TestApprovalPolicy 显式设置各模式来覆盖。
    "TOOL_APPROVAL_MODE": "auto",
    # 编码工具默认不注册进全局注册表：需要它们的用例自己注册，
    # 避免污染其他用例看到的工具列表
    "CODING_TOOLS_ENABLED": "false",
    # 上传目录挪到临时区，别往仓库里写
    "UPLOAD_DIR": os.path.join(os.path.sep, "tmp", "selfagent-test-uploads"),
}
for _k, _v in _BLACKHOLE.items():
    os.environ[_k] = _v

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_external_io(monkeypatch):
    """短路所有外部连接。

    黑洞端口只保证「写不进真实库」，不保证快：pymongo 的 server selection、
    neo4j 的 connection_timeout、psycopg_pool 的 open(wait=True) 面对
    「连接被拒」都会重试到各自的超时。而每个 TestClient(app) 都会完整跑一遍
    lifespan，十几个用例就是十几轮超时——整套测试 90% 的时间耗在这里。

    测试本来就跑内存态（MemorySaver + InMemoryStore），直接短路。
    """
    import app.memory.checkpointer as cp
    import app.memory.pg as pg
    import app.memory.store as store
    from app.db.manager import db_manager

    async def _anoop(*args, **kwargs):
        return None

    # 三个模块都要打：store/checkpointer 用的是 `from app.memory.pg import get_pg_pool`，
    # 持有的是函数对象本身的引用，只改 pg 模块属性对它们无效。
    # （症状是每个用例的 fixture setup 都恰好卡 5.01 秒——正好是连接池超时；
    #  而 lifespan 退出时 close_pg_pool() 会把「已失败」标记清掉，所以每轮都重来。）
    monkeypatch.setattr(pg, "get_pg_pool", _anoop)
    monkeypatch.setattr(store, "get_pg_pool", _anoop)
    monkeypatch.setattr(cp, "get_pg_pool", _anoop)
    monkeypatch.setattr(db_manager, "connect", _anoop)
    monkeypatch.setattr(db_manager, "disconnect", _anoop)


@pytest.fixture(autouse=True)
def _fresh_memory_singletons():
    """每个用例前后清掉记忆层单例，避免用例之间互相看见对方写的记忆。"""
    import app.memory.store as store_mod

    store_mod._store = None
    store_mod._memory_service = None
    yield
    store_mod._store = None
    store_mod._memory_service = None
