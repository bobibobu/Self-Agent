# 开发流程文档

## 文档清单

- [环境搭建指南](01-setup.md) —— 从零跑起项目
- 开发规范 ⏳ *（未编写）* —— 代码风格、提交规范（Phase 5）
- 调试技巧 ⏳ *（未编写）* —— 日志查看、断点、Mock（Phase 5）
- 测试指南 ⏳ *（未编写）* —— 单元/集成测试（Phase 5）
- 部署指南 ⏳ *（未编写）* —— 生产部署（Phase 5）

> 调试、测试、部署相关内容目前散落在这几处：
> - 测试怎么跑、怎么组织 → [项目总览·开发与测试](../00-overview/README.md#七开发与测试)
> - 排查常见问题 → [从零读懂·第7章](../00-overview/02-从零读懂.md)
> - 部署与基础设施 → [infra/README.md](../../infra/README.md)

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
python scripts/benchmark.py           # 性能基准：框架层 QPS（mock LLM，无需 DB/key）

# 代码质量
ruff check app/                       # lint
ruff format app/                      # 格式化

# 测试（Phase 5）
pytest tests/                         # 跑测试
```
