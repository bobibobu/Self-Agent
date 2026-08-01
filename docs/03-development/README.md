# 开发流程文档

## 文档清单

- [环境搭建指南](01-setup.md) —— 从零跑起项目
- [开发规范](02-conventions.md) ⏳ —— 代码风格、提交规范（Phase 5）
- [调试技巧](03-debugging.md) ⏳ —— 日志查看、断点、Mock（Phase 5）
- [测试指南](04-testing.md) ⏳ —— 单元/集成测试（Phase 5）
- [部署指南](05-deployment.md) ⏳ —— 生产部署（Phase 5）

## 开发工作流

```
改代码 → 本地验证(python scripts/verify_agent.py) → 起 uvicorn 测试 → 提交
```

### 常用命令速查

```bash
# 基础设施
cd infra && docker compose up -d      # 起数据库
docker compose down                   # 停
docker compose logs -f postgres       # 看日志

# 应用
uv run uvicorn app.main:app --reload  # 启动（热重载）
python scripts/verify_agent.py        # 快速验证核心逻辑（无需 DB/key）

# 代码质量
ruff check app/                       # lint
ruff format app/                      # 格式化

# 测试（Phase 5）
pytest tests/                         # 跑测试
```
