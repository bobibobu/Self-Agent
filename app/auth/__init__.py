"""
用户认证（JWT）
==============
提供：
- 密码哈希（bcrypt）
- JWT 签发与校验
- FastAPI 依赖：get_current_user（从请求头解析 token）
- 请求级用户/租户上下文

设计：
- auth_enabled=False 时，认证依赖放行（返回默认用户），便于 dev 调试
- auth_enabled=True 时，所有受保护端点必须有有效 JWT
- 多租户：token 内含 tenant_id，数据按租户隔离
"""
