// ===================================================================
// Self-Agent MongoDB 初始化脚本
// -------------------------------------------------------------------
// 容器首次启动时自动执行。创建集合与索引。
// ===================================================================

// 切换到业务库（与 MONGO_INITDB_DATABASE 一致）
db = db.getSiblingDB('selfagent');

// ------------------------------------------------------------------
// 对话事件日志集合
//   记录每轮对话的原始输入输出、工具调用、耗时等，便于回溯分析。
//   形态多变、写多读少，适合 Mongo。
// ------------------------------------------------------------------
db.createCollection('conversation_events');
db.conversation_events.createIndex({ "thread_id": 1, "ts": 1 });
db.conversation_events.createIndex({ "user_id": 1 });

// ------------------------------------------------------------------
// 应用日志集合（结构化日志的落盘副本，可选）
// ------------------------------------------------------------------
db.createCollection('app_logs');
db.app_logs.createIndex({ "ts": 1 });
db.app_logs.createIndex({ "level": 1 });

print('Self-Agent MongoDB initialized: collections conversation_events, app_logs created.');
