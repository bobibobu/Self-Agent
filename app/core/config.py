"""
应用配置中心
-------------
基于 pydantic-settings，所有配置项从环境变量 / .env 文件读取，
做到「配置即代码」、类型安全、无硬编码密钥。

加载优先级（高 → 低）：
    真实环境变量  >  .env 文件  >  代码内默认值
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。通过 `get_settings()` 获取单例。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    app_name: str = "Self-Agent"
    app_env: Literal["dev", "staging", "prod"] = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"

    # ---------- LLM ----------
    llm_default_provider: Literal["glm", "openai", "anthropic"] = "glm"

    # GLM（走 OpenAI 兼容协议）
    glm_api_key: str = ""
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4/"
    glm_model: str = "glm-4.5-flash"

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1/"
    openai_model: str = "gpt-4o-mini"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    anthropic_model: str = "claude-haiku-4-5-20251001"

    # LLM 调用超时（秒）与重试次数。没有超时的话单次卡死会一直占着连接。
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # ---------- 向量化（长期记忆 / RAG 的语义检索）----------
    # auto：跟随默认 LLM provider 自动选；none：强制用哈希伪向量（仅调试）
    embedding_provider: Literal["auto", "glm", "openai", "none"] = "auto"
    embedding_model: str = ""   # 留空用 provider 默认（glm: embedding-3 / openai: text-embedding-3-small）
    embedding_dims: int = 0     # 留空用 provider 默认（glm: 2048 / openai: 1536）

    # ---------- PostgreSQL ----------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "selfagent"
    postgres_password: str = "selfagent123"
    postgres_db: str = "selfagent"
    # LangGraph checkpointer/store 共享连接池的上限
    postgres_pool_max_size: int = 10

    # ---------- MongoDB ----------
    mongo_host: str = "localhost"
    mongo_port: int = 27017
    mongo_user: str = "selfagent"
    mongo_password: str = "selfagent123"
    mongo_db: str = "selfagent"

    # ---------- Redis ----------
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0

    # ---------- Neo4j ----------
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "selfagent123"

    # ---------- MCP（Model Context Protocol）----------
    # 是否启用 MCP client（连接外部 MCP server 获取工具）
    mcp_client_enabled: bool = True
    # 外部 MCP server 配置文件（JSON），格式见 mcp_servers.json.example
    mcp_servers_config: str = "mcp_servers.json"
    # 是否启用 MCP server（把内置工具暴露给外部 Agent）
    mcp_server_enabled: bool = False
    mcp_server_port: int = 9000

    # ---------- Agent ----------
    # agent↔tools 循环的最大步数（每个工具回合消耗 2 步）
    agent_recursion_limit: int = 25
    # 单个工具结果注入上下文的最大字符数（防止某个工具返回 1MB 撑爆上下文）
    tool_result_max_chars: int = 4000

    # ---------- Skill 系统 ----------
    skills_enabled: bool = True

    # ---------- A2A 协议 ----------
    # 是否启用 A2A server（暴露本 Agent 给外部 Agent 调用）
    a2a_enabled: bool = True
    a2a_base_url: str = "http://localhost:8000"
    # delegate_to_agent 允许调用的目标 Agent 白名单（逗号分隔）。
    # 为空则允许任意（仅开发态安全）；生产务必配置，防 SSRF。
    a2a_delegate_allowlist: str = ""

    # ---------- Hermes 自我进化 ----------
    # 能力 A：对话后自动抽取记忆/画像（被动学习）
    hermes_learning_enabled: bool = True
    # 能力 B：反思+提示词自优化（主动进化，需手动触发 /evolution/reflect）
    hermes_reflection_enabled: bool = True

    # ---------- 用户认证 ----------
    # JWT 密钥（生产必须改为随机强密钥）
    jwt_secret: str = "self-agent-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    # 是否启用认证（dev 可关闭，便于调试；生产必须开）
    auth_enabled: bool = False

    # 管理员用户名（逗号分隔）。登录时写入 token 的 role claim，
    # 决定谁能调用 /evolution、/stats、/metrics 等管理面接口。
    admin_usernames: str = ""

    # ---------- 多租户 ----------
    # 是否启用多租户隔离（启用后数据按 tenant_id 隔离）
    multi_tenant_enabled: bool = False
    # 允许的租户 ID（逗号分隔）。多租户启用时，客户端声明的租户必须在此名单内，
    # 否则拒绝——防止任意注册进他人租户。名单为空则只允许 default。
    tenant_allowlist: str = ""
    # 客户端声明租户用的请求头（仅多租户启用时生效）
    tenant_header: str = "X-Tenant-Id"

    # ---------- 限流 ----------
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60

    # ---------- 文件上传 ----------
    upload_dir: str = "data/uploads"
    upload_max_size_mb: int = 20

    # ---------- 便捷派生属性 ----------
    @property
    def postgres_dsn(self) -> str:
        """异步 Postgres 连接串（asyncpg 格式，纯 postgresql://）。"""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_dsn_asyncpg(self) -> str:
        """asyncpg 专用：与 postgres_dsn 相同（纯 postgresql://）。"""
        return self.postgres_dsn

    @property
    def postgres_dsn_sync(self) -> str:
        """同步 Postgres 连接串（LangGraph PostgresSaver 用 psycopg 格式）。"""
        return self.postgres_dsn

    @property
    def mongo_uri(self) -> str:
        return f"mongodb://{self.mongo_user}:{self.mongo_password}@{self.mongo_host}:{self.mongo_port}"

    @property
    def redis_url(self) -> str:
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"


@lru_cache
def get_settings() -> Settings:
    """返回配置单例（lru_cache 保证全局只读一次环境变量）。"""
    return Settings()
