"""LLM 配置在线热替换（/admin/llm-config）
==========================================
「换个 key 不重启」：

1. 管理员 POST 新 key → 内存配置原地更新 + 各层 lru_cache 客户端失效
   + 写回 env 文件持久化——下一次 LLM/embedding 调用按新配置重建。
2. 非管理员（认证开启时）403。
3. embedding 的 provider/模型/维度变化会触发 reindex_required 提示
   （已入库旧向量维度失配，需要重启重建 store 并重新 ingest）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.dependencies import CurrentUser, get_current_user
from app.core.config import get_settings

_ADMIN = CurrentUser(user_id="admin1", username="admin1", role="admin")
_USER = CurrentUser(user_id="u1", username="u1", role="user")


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c, app


@pytest.fixture
def isolated_env_file():
    """把持久化目标指到临时文件，绝不碰开发者真实的 .env。"""
    import tempfile

    s = get_settings()
    saved = s.env_file_path
    with tempfile.TemporaryDirectory() as td:
        s.env_file_path = str(Path(td) / "runtime.env")
        yield s.env_file_path
        s.env_file_path = saved


@pytest.fixture
def restore_keys():
    """测试会改全局 Settings 与 lru_cache，退出前恢复。"""
    s = get_settings()
    saved = (s.glm_api_key, s.openai_api_key, s.glm_model)
    yield s
    s.glm_api_key, s.openai_api_key, s.glm_model = saved
    from app.llm.factory import reset_llm_clients
    from app.memory.embeddings import reset_embedding_caches
    from app.rag.service import reset_rag_utility_llm

    reset_llm_clients()
    reset_embedding_caches()
    reset_rag_utility_llm()


class TestLlmKeyHotSwap:
    def test_swap_key_takes_effect_without_restart(self, client, isolated_env_file, restore_keys):
        """换 key 后不重启：配置更新、客户端重建、env 文件持久化。"""
        c, app = client
        app.dependency_overrides[get_current_user] = lambda: _ADMIN
        s = get_settings()
        s.glm_api_key = "old-key-123456"

        from app.llm.factory import get_llm_client

        old_client = get_llm_client()
        assert old_client._client.api_key == "old-key-123456"

        resp = c.post("/admin/llm-config", json={"glm_api_key": "new-key-987654"})
        assert resp.status_code == 200
        body = resp.json()["config"]
        assert body["glm_api_key_masked"].startswith("new-key-")
        assert body["embedding_reindex_required"] is False

        # ① 内存配置已变
        assert s.glm_api_key == "new-key-987654"
        # ② 缓存已失效：重建的客户端拿到新 key（不重启即生效的核心断言）
        assert get_llm_client() is not old_client
        assert get_llm_client()._client.api_key == "new-key-987654"
        # ③ 已写回 env 文件，重启后仍生效（set_key 会给值加引号，解析回读等价）
        content = Path(isolated_env_file).read_text(encoding="utf-8")
        assert "GLM_API_KEY" in content and "new-key-987654" in content
        app.dependency_overrides.pop(get_current_user, None)

    def test_persist_false_only_touches_memory(self, client, isolated_env_file, restore_keys):
        """persist=false：只影响当前进程，不写盘。"""
        c, app = client
        app.dependency_overrides[get_current_user] = lambda: _ADMIN
        resp = c.post("/admin/llm-config", json={"glm_api_key": "ephemeral", "persist": False})
        assert resp.status_code == 200
        assert get_settings().glm_api_key == "ephemeral"
        assert not __import__("os").path.exists(isolated_env_file)
        app.dependency_overrides.pop(get_current_user, None)

    def test_non_admin_forbidden_when_auth_enabled(self, client, isolated_env_file, restore_keys, monkeypatch):
        """认证开启时普通用户 403；匿名/dev 形态不拦（见 require_admin 语义）。"""
        c, app = client
        s = get_settings()
        monkeypatch.setattr(s, "auth_enabled", True)
        app.dependency_overrides[get_current_user] = lambda: _USER
        resp = c.post("/admin/llm-config", json={"glm_api_key": "x"})
        assert resp.status_code == 403
        app.dependency_overrides.pop(get_current_user, None)

    def test_reindex_required_when_embedding_dims_change(self, client, isolated_env_file, restore_keys, monkeypatch):
        """embedding 维度变化（哈希伪向量 → 真实向量）必须提示重建索引。"""
        c, app = client
        app.dependency_overrides[get_current_user] = lambda: _ADMIN
        s = get_settings()
        assert s.glm_api_key == ""  # conftest 黑洞化后是哈希降级形态
        # conftest 把 EMBEDDING_PROVIDER 钉成了 none（强制哈希）；真实场景换 key
        # 时 provider 是 auto，这里恢复成 auto 才能模拟「加 key 后 provider 翻转」
        monkeypatch.setattr(s, "embedding_provider", "auto")

        resp = c.post("/admin/llm-config", json={
            "glm_api_key": "k-1234567890",
        })
        body = resp.json()["config"]
        # provider 从 none(256 维哈希) 翻转为 glm embedding-3（2048 维）→ 维度失配
        assert body["embedding_reindex_required"] is True
        assert body["embedding_dims"] == 2048
        app.dependency_overrides.pop(get_current_user, None)

    def test_get_masks_keys(self, client, isolated_env_file, restore_keys):
        """GET 状态接口：key 必须打码，不能整把返回。"""
        c, app = client
        app.dependency_overrides[get_current_user] = lambda: _ADMIN
        get_settings().glm_api_key = "sk-very-secret-key-value-123"
        resp = c.get("/admin/llm-config")
        assert resp.status_code == 200
        masked = resp.json()["glm_api_key_masked"]
        assert "very-secret" not in masked
        assert "****" in masked or "..." in masked
        app.dependency_overrides.pop(get_current_user, None)
