"""
沙箱测试
========
断言的是**实际拦截效果**，不是「配置项有没有设对」。

沙箱这种东西最危险的失败模式是「看起来开着，其实没生效」——
所以核心用例都真的去读一个工作区外的文件、真的去写一个工作区外的路径，
看它到底成不成功。

运行：pytest tests/test_sandbox.py -v
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def project(tmp_path, monkeypatch):
    """临时工作区 + 一个位于工作区外的"机密文件"。

    机密文件必须放在系统临时目录**之外**：沙箱会给一个私有 tmp 目录授权，
    把靶子放在 /tmp 里等于在测自己。
    """
    (tmp_path / "code.py").write_text("print('inside')\n", encoding="utf-8")

    outside = Path.home() / f".selfagent-sbx-test-{os.getpid()}"
    outside.mkdir(exist_ok=True)
    (outside / "id_rsa").write_text("PRIVATE-KEY-CONTENT\n", encoding="utf-8")

    from app.workspace import get_workspace, set_workspace

    set_workspace(tmp_path)
    yield tmp_path, outside

    get_workspace.cache_clear()
    import shutil

    shutil.rmtree(outside, ignore_errors=True)


@pytest.fixture
def sandbox_on(monkeypatch):
    from app.core.config import get_settings

    s = get_settings()
    old_enabled, old_backend = s.sandbox_enabled, s.sandbox_backend
    s.sandbox_enabled = True
    s.sandbox_backend = "auto"
    yield s
    s.sandbox_enabled, s.sandbox_backend = old_enabled, old_backend


def _sandbox_active() -> bool:
    from app.sandbox import SandboxBackend, detect_backend

    return detect_backend("auto") is not SandboxBackend.NONE


needs_sandbox = pytest.mark.skipif(
    not _sandbox_active(), reason="当前环境没有可用的沙箱后端（bwrap / Landlock）",
)


# ==================== 后端探测 ====================


class TestBackendDetection:
    def test_none_when_explicitly_disabled(self):
        from app.sandbox import SandboxBackend, detect_backend

        assert detect_backend("none") is SandboxBackend.NONE

    def test_detection_is_capability_based_not_wishful(self):
        """探测必须基于**实跑验证**，不能只看二进制存在或 ABI 号。

        bwrap 装了但没有非特权 user namespace、Landlock 报了 ABI
        但具体 ruleset 被拒——这两种情况都会让「以为有沙箱」变成事实上的裸奔。
        """
        from app.sandbox import _bwrap_available, _landlock_available, detect_backend

        backend = detect_backend("auto")
        if backend.value == "bwrap":
            assert _bwrap_available()
        elif backend.value == "landlock":
            assert _landlock_available()

    def test_describe_is_honest_about_no_protection(self, monkeypatch):
        from app.core.config import get_settings
        from app.sandbox import describe

        s = get_settings()
        old = s.sandbox_enabled
        s.sandbox_enabled = False
        try:
            assert "禁用" in describe()
        finally:
            s.sandbox_enabled = old

    def test_landlock_only_claims_filesystem(self):
        """Landlock 不管网络，描述里必须写明——否则用户会以为断网了。"""
        from app.core.config import get_settings
        from app.sandbox import SandboxBackend, describe, detect_backend

        s = get_settings()
        old_e, old_b = s.sandbox_enabled, s.sandbox_backend
        s.sandbox_enabled, s.sandbox_backend = True, "landlock"
        try:
            if detect_backend("landlock") is SandboxBackend.LANDLOCK:
                assert "不限制网络" in describe()
        finally:
            s.sandbox_enabled, s.sandbox_backend = old_e, old_b


# ==================== 实际拦截效果 ====================


@needs_sandbox
class TestActualIsolation:
    @pytest.mark.asyncio
    async def test_workspace_stays_usable(self, project, sandbox_on):
        """沙箱不能把正常工作也挡了——工作区内读写必须照常。"""
        from app.agent.tools.shell import run_command

        out = await run_command.ainvoke({"command": "cat code.py"})
        assert "inside" in out and "[成功" in out

        out = await run_command.ainvoke({"command": "touch newfile.txt"})
        assert "[成功" in out
        assert (project[0] / "newfile.txt").exists()

    @pytest.mark.asyncio
    async def test_cannot_read_outside_workspace(self, project, sandbox_on):
        """核心断言：工作区外的密钥读不到。

        这条挡的是「审批通过的 pytest 因为项目里有恶意 conftest.py
        而读走 ~/.ssh/id_rsa」这条路径。
        """
        _, outside = project
        from app.agent.tools.shell import run_command

        out = await run_command.ainvoke({"command": f"cat {outside / 'id_rsa'}"})
        assert "PRIVATE-KEY-CONTENT" not in out, f"密钥泄漏了：{out}"

    @pytest.mark.asyncio
    async def test_cannot_write_outside_workspace(self, project, sandbox_on):
        _, outside = project
        from app.agent.tools.shell import run_command

        target = outside / "pwned.txt"
        await run_command.ainvoke({"command": f"touch {target}"})
        assert not target.exists(), "沙箱外写入成功了"

    @pytest.mark.asyncio
    async def test_reports_which_backend_is_active(self, project, sandbox_on):
        """输出必须带上生效的后端——「以为有沙箱其实没有」比「知道没有」危险得多。"""
        from app.agent.tools.shell import run_command

        out = await run_command.ainvoke({"command": "echo hi"})
        assert "sandbox=" in out


class TestNoSandboxIsLoud:
    @pytest.mark.asyncio
    async def test_none_backend_is_flagged_in_output(self, project):
        from app.core.config import get_settings
        from app.agent.tools.shell import run_command

        s = get_settings()
        old = s.sandbox_enabled
        s.sandbox_enabled = False
        try:
            out = await run_command.ainvoke({"command": "echo hi"})
            assert "sandbox=none" in out and "⚠️" in out, "无沙箱必须显眼地标出来"
        finally:
            s.sandbox_enabled = old


# ==================== bwrap 命令行构造 ====================


class TestBwrapArgv:
    def test_hides_home_and_binds_workspace(self, tmp_path):
        from app.sandbox import _bwrap_argv

        argv = _bwrap_argv(["echo", "hi"], tmp_path, tmp_path, allow_network=False)
        joined = " ".join(argv)

        assert "--bind" in argv and str(tmp_path) in argv, "工作区必须可写"
        assert "--unshare-net" in argv, "默认应切断网络"
        assert "--die-with-parent" in argv, "父进程退出后不能留孤儿"
        # 真实 HOME 不能出现在挂载里，否则 ~/.ssh ~/.aws 就暴露了
        assert str(Path.home()) not in joined or "--tmpfs" in joined
        assert argv[-2:] == ["echo", "hi"]

    def test_network_can_be_allowed(self, tmp_path):
        from app.sandbox import _bwrap_argv

        argv = _bwrap_argv(["echo", "hi"], tmp_path, tmp_path, allow_network=True)
        assert "--unshare-net" not in argv


# ==================== 私有临时目录 ====================


class TestPrivateTmp:
    def test_tmp_is_private_not_shared(self):
        """不能把整个 /tmp 授予写权限——那样别人放在 /tmp 的凭据就都能读。"""
        import tempfile

        from app.sandbox import _private_tmp

        tmp = Path(_private_tmp())
        assert tmp.is_dir()
        assert tmp != Path(tempfile.gettempdir()), "必须是专属子目录而非整个 /tmp"
        assert oct(tmp.stat().st_mode)[-3:] == "700", "只应本人可访问"

    def test_landlock_sets_tmpdir_env(self, tmp_path):
        """把 TMPDIR 指向私有目录，工具链照常工作但暴露面收窄。"""
        from app.sandbox import SandboxBackend, wrap_command

        sbx = wrap_command(["echo"], workspace=tmp_path, cwd=tmp_path, allow_network=False)
        if sbx.backend is SandboxBackend.LANDLOCK:
            assert sbx.env.get("TMPDIR", "").startswith(str(Path(sbx.env["TMPDIR"]).parent))
            assert "selfagent-sbx" in sbx.env["TMPDIR"]
