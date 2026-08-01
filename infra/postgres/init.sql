-- ===================================================================
-- Self-Agent PostgreSQL 初始化脚本
-- -------------------------------------------------------------------
-- 容器首次启动时自动执行（仅初始化一次，数据卷存在后不再运行）。
-- LangGraph 的 PostgresSaver / PostgresStore 会自行创建自己的表，
-- 这里只做：扩展安装、业务库表、注释。
-- ===================================================================

-- 启用扩展 ----------------------------------------------------------
-- pgcrypto: 提供 gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- pg_trgm: 模糊匹配（如用户搜索）
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- vector: LangGraph PostgresStore 的语义索引依赖它（长期记忆 / RAG 检索）。
-- 需要 pgvector 镜像；用原版 postgres 镜像时这句会失败，
-- 应用会自动降级为「持久化但无语义索引」并打 WARNING。
CREATE EXTENSION IF NOT EXISTS vector;

-- ------------------------------------------------------------------
-- 用户表（租户/账户体系的最小骨架）
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username    VARCHAR(64)  UNIQUE NOT NULL,
    email       VARCHAR(128) UNIQUE,
    nickname    VARCHAR(64),
    status      VARCHAR(16)  NOT NULL DEFAULT 'active',  -- active / disabled
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE users IS '用户/账户主表';

-- 认证与租户扩展列（幂等添加，兼容已有数据卷）
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(256);
ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL DEFAULT 'default';
ALTER TABLE users ADD COLUMN IF NOT EXISTS user_ref VARCHAR(128);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_tenant_username ON users(tenant_id, username);
CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id);

-- ------------------------------------------------------------------
-- 会话表（记录每个对话 thread 的元信息）
-- thread_id 与 LangGraph checkpointer 的 thread_id 对应
-- ------------------------------------------------------------------
-- user_id 用 VARCHAR 而非 UUID+外键：应用同时支持匿名模式与 CLI，
-- 此时 user_id 是 'anonymous' / 'web-user' 这类非 UUID 字符串。
-- 原来定义成 UUID REFERENCES users(id) 会让这些写入直接报错，
-- 而调用处的 except 会把错误吞掉，表现为「接口 200 但会话列表永远是空的」。
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id   VARCHAR(128) NOT NULL,
    user_id     VARCHAR(128),
    title       VARCHAR(256),
    tenant_id   VARCHAR(64)  NOT NULL DEFAULT 'default',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE conversations IS '会话(thread)元数据，与 LangGraph checkpointer 的 thread_id 对应';

-- 兼容已有数据卷：把旧结构就地升级（init.sql 只在首次建卷时跑，
-- 已有环境请手动执行 infra/postgres/migrations/ 下的脚本）
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL DEFAULT 'default';
ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_user_id_fkey;
ALTER TABLE conversations ALTER COLUMN user_id TYPE VARCHAR(128) USING user_id::text;

-- 唯一性按 (tenant_id, thread_id)：thread_id 全局唯一会让两个租户
-- 用同一个 thread_id（比如接口默认值 "default"）时互相踩踏。
ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_thread_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_tenant_thread
    ON conversations(tenant_id, thread_id);

-- 索引 --------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_user ON conversations(tenant_id, user_id);
-- 列表查询是 WHERE tenant_id=? [AND user_id=?] ORDER BY updated_at DESC
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_updated
    ON conversations(tenant_id, updated_at DESC);

-- 初始演示用户（密码占位，真实项目应单独做鉴权）-------------------
INSERT INTO users (username, email, nickname)
VALUES ('demo', 'demo@self-agent.local', '演示用户')
ON CONFLICT (username) DO NOTHING;
