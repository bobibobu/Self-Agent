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
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id   VARCHAR(128) UNIQUE NOT NULL,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    title       VARCHAR(256),
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE conversations IS '会话(thread)元数据，与 LangGraph checkpointer 的 thread_id 对应';

-- 会话表也加 tenant_id（多租户隔离）
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_user ON conversations(tenant_id, user_id);

-- 索引 --------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);

-- 初始演示用户（密码占位，真实项目应单独做鉴权）-------------------
INSERT INTO users (username, email, nickname)
VALUES ('demo', 'demo@self-agent.local', '演示用户')
ON CONFLICT (username) DO NOTHING;
