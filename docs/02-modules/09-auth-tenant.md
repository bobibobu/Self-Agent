# 用户认证与多租户

> 对齐成熟产品的安全基线：JWT 认证 + 多租户数据隔离 + 限流防护。

---

## 一、用户认证（JWT）

### 机制
- 密码：bcrypt 哈希（直接用 bcrypt 库，不依赖已停维的 passlib）
- Token：JWT（HS256），claims 含 user_id / tenant_id / username / 过期时间
- 传输：`Authorization: Bearer <token>` 头

### 端点
| 端点 | 说明 |
|---|---|
| `POST /auth/register` | 注册（用户名+密码），返回 JWT |
| `POST /auth/login` | 登录，返回 JWT |
| `GET /auth/me` | 当前用户信息 |

### 配置开关
```ini
AUTH_ENABLED=false   # dev 可关（便于调试）；生产必须 true
JWT_SECRET=强随机密钥
JWT_EXPIRE_HOURS=24
```
`AUTH_ENABLED=false` 时，受保护端点放行（返回默认匿名用户），不阻断调试。

### 设计要点
- 密码超 72 字节自动截断（bcrypt 限制），避免报错
- 无效/过期 token 返回 401（统一 AuthError）
- 密码哈希绝不返回给客户端

---

## 二、多租户隔离

### 隔离维度
启用后，数据按 `tenant_id` 隔离，不同租户互不可见：

| 数据 | 隔离方式 |
|---|---|
| 长期记忆（store） | namespace 加前缀：`("tenant", tenant_id, "user", user_id)` |
| 用户画像（Neo4j） | user_id 加前缀：`tenant_id:user_id` |
| 会话（conversations） | tenant_id 列过滤 |
| 对话日志（Mongo） | 每条带 tenant_id |

### 关键：tenant_id 不可伪造
`tenant_id` 来自**已验证的 JWT claims**（`decode_token` 解出），客户端无法篡改。请求进入时由认证依赖注入，下游所有服务拿到的是可信身份。

### 配置
```ini
MULTI_TENANT_ENABLED=false   # 默认关闭；开启后全链路按租户隔离
```
关闭时退化为不隔离（兼容单租户场景）。

---

## 三、限流（Redis 滑动窗口）

### 机制
- 按"用户（已认证）或 IP（未认证）+ 分钟"计数
- 超 `RATE_LIMIT_PER_MINUTE` 返回 429 + Retry-After
- Redis 不可用时**放行**（不因限流组件故障阻断服务）

### 豁免
`/health`、`/docs`、`/auth/login` 等不计入限流。

### 配置
```ini
RATE_LIMIT_ENABLED=true
RATE_LIMIT_PER_MINUTE=60
```

---

## 四、架构位置（为什么核心层不用改）

认证/租户/限流都在**新增的业务层与中间件层**：

```
请求 → 限流中间件 → API层(Depends认证) → 业务层(会话/统计) → Agent核心
         ↑新增            ↑新增                ↑新增           ↑不动
```

核心能力层（LLM/记忆/工具/MCP/A2A）只认 user_id 字符串，**完全不感知认证与租户**——这正是分层架构的价值。

---

## 五、面试要点

**Q: 为什么不用 passlib？**
A: passlib 已停止维护，且与 bcrypt 5.0 不兼容（用了已删除的 `bcrypt.__about__.__version__`）。直接用 bcrypt 库更轻量、更可控。

**Q: 多租户隔离为什么不用独立的数据库/Schema？**
A: 那是物理隔离（每租户一库），成本高、运维重。本项目用逻辑隔离（namespace 前缀 + 列过滤），适合中小规模 SaaS。规模到上千租户再考虑分库分表。

**Q: 限流为什么 Redis 不可用就放行？**
A: 限流是"防滥用"的辅助措施，不是核心功能。若因 Redis 故障就拒绝所有请求，反而造成服务不可用——这违背"核心链路尽量独立于非关键依赖"的韧性原则。
