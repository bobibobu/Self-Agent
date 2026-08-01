-- ===================================================================
-- 迁移 001：修正 conversations 表结构
-- -------------------------------------------------------------------
-- 背景：init.sql 只在 Postgres 数据卷**首次创建**时执行一次，
--       已有环境不会自动应用后续改动，需要手动跑本脚本。
--
-- 执行：
--   docker exec -i selfagent-postgres \
--     psql -U selfagent -d selfagent < infra/postgres/migrations/001_fix_conversations_schema.sql
--
-- 修的问题：
--   1. user_id 原为 UUID REFERENCES users(id)，但应用在匿名/CLI 模式下
--      写入的是 'anonymous'、'web-user' 这类非 UUID 字符串 → asyncpg 报错
--      → 被调用处的 except 吞掉 → 会话记录写不进去，前端会话列表恒为空。
--   2. thread_id 全局 UNIQUE，多租户下两个租户用同一 thread_id 会互相踩踏
--      （接口默认值就是 "default"，极易撞上）。
--   3. 缺少列表查询用的排序索引。
--
-- 本脚本幂等，可重复执行。
-- ===================================================================

BEGIN;

-- 1. 放宽 user_id 类型并去掉外键
ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_user_id_fkey;
ALTER TABLE conversations ALTER COLUMN user_id TYPE VARCHAR(128) USING user_id::text;

-- 2. 补 tenant_id（可能是更早版本的库）
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(64) NOT NULL DEFAULT 'default';

-- 3. 唯一约束改为 (tenant_id, thread_id)
ALTER TABLE conversations DROP CONSTRAINT IF EXISTS conversations_thread_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_tenant_thread
    ON conversations(tenant_id, thread_id);

-- 4. 列表查询索引
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_user ON conversations(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_updated
    ON conversations(tenant_id, updated_at DESC);

COMMIT;
