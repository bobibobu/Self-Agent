"""
编码工具测试
============
重点是**安全边界**，不是「功能能不能跑通」。

模型会产出 `../../etc/passwd`、`rm -rf /`、`cat .env` 这类东西。
工作区禁闭与审批闸门是唯一的防线，所以这里的断言主要在证明它们挡得住。

运行：pytest tests/test_coding_tools.py -v
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def ws(tmp_path):
    """在临时目录建一个小项目，并把它设为当前工作区。"""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("def main():\n    print('hello')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo\n项目说明\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET_KEY=super-secret-value\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n", encoding="utf-8")
    (tmp_path / "debug.log").write_text("noise\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("x", encoding="utf-8")

    from app.workspace import set_workspace

    workspace = set_workspace(tmp_path)
    yield workspace

    from app.workspace import get_workspace
    get_workspace.cache_clear()


# ==================== 工作区禁闭 ====================


class TestWorkspaceConfinement:
    def test_rejects_parent_traversal(self, ws):
        from app.workspace import WorkspaceError

        for evil in ["../../etc/passwd", "../outside.txt", "app/../../escape"]:
            with pytest.raises(WorkspaceError):
                ws.resolve(evil)

    def test_rejects_absolute_path_outside(self, ws):
        from app.workspace import WorkspaceError

        with pytest.raises(WorkspaceError):
            ws.resolve("/etc/passwd")

    def test_rejects_symlink_escape(self, ws, tmp_path):
        """符号链接逃逸：字符串前缀匹配挡不住，必须先 resolve 再判归属。"""
        from app.workspace import WorkspaceError

        outside = tmp_path.parent / "outside_secret.txt"
        outside.write_text("机密", encoding="utf-8")
        link = ws.root / "innocent_link"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("当前环境不支持创建符号链接")

        with pytest.raises(WorkspaceError):
            ws.resolve("innocent_link")

    def test_allows_paths_inside(self, ws):
        assert ws.resolve("app/main.py").is_file()
        assert ws.resolve("./README.md").is_file()
        # 新文件（尚不存在）也应放行——写入场景需要
        assert ws.resolve("newdir/new.txt").name == "new.txt"

    def test_ignores_gitignore_and_builtin(self, ws):
        assert ws.is_ignored(ws.root / "debug.log")           # .gitignore
        assert ws.is_ignored(ws.root / "node_modules" / "junk.js")  # 内置黑名单
        assert not ws.is_ignored(ws.root / "app" / "main.py")


# ==================== 文件工具 ====================


class TestFileTools:
    @pytest.mark.asyncio
    async def test_read_file_with_line_numbers(self, ws):
        from app.agent.tools.files import read_file

        out = await read_file.ainvoke({"path": "app/main.py"})
        assert "def main():" in out
        assert "1|" in out, "应带行号，方便模型精确引用"

    @pytest.mark.asyncio
    async def test_read_file_refuses_secrets(self, ws):
        """.env 里的密钥绝不能进上下文——进了就会随 prompt 发给模型厂商。"""
        from app.agent.tools.files import read_file

        out = await read_file.ainvoke({"path": ".env"})
        assert "super-secret-value" not in out
        assert "拒绝" in out

    @pytest.mark.asyncio
    async def test_read_file_refuses_traversal(self, ws):
        from app.agent.tools.files import read_file

        out = await read_file.ainvoke({"path": "../../etc/passwd"})
        assert "错误" in out and "工作区外" in out

    @pytest.mark.asyncio
    async def test_grep_skips_ignored_and_secrets(self, ws):
        from app.agent.tools.files import grep_files

        # 注意：不能断言"输出里不含该字符串"——未命中时工具会回显搜索词本身。
        # 要断言的是「没有命中任何文件」，即 .env 没被扫进来。
        out = await grep_files.ainvoke({"query": "super-secret-value"})
        assert "没有找到" in out, f"grep 把 .env 的内容捞出来了：{out}"
        assert ".env" not in out

        out2 = await grep_files.ainvoke({"query": "noise"})
        assert "没有找到" in out2, f"被 gitignore 的文件不该被搜到：{out2}"

    @pytest.mark.asyncio
    async def test_write_and_edit_roundtrip(self, ws):
        from app.agent.tools.files import edit_file, read_file, write_file

        await write_file.ainvoke({"path": "app/new.py", "content": "x = 1\ny = 2\n"})
        assert (ws.root / "app" / "new.py").read_text() == "x = 1\ny = 2\n"

        await edit_file.ainvoke({"path": "app/new.py", "old_text": "x = 1", "new_text": "x = 42"})
        assert "x = 42" in (ws.root / "app" / "new.py").read_text()
        assert "x = 42" in await read_file.ainvoke({"path": "app/new.py"})

    @pytest.mark.asyncio
    async def test_edit_refuses_ambiguous_match(self, ws):
        """出现多处时不猜该改哪一处——猜错就是静默改坏代码。"""
        from app.agent.tools.files import edit_file

        (ws.root / "dup.py").write_text("a = 1\na = 1\n", encoding="utf-8")
        out = await edit_file.ainvoke({"path": "dup.py", "old_text": "a = 1", "new_text": "a = 2"})
        assert "2 次" in out and "错误" in out
        assert (ws.root / "dup.py").read_text() == "a = 1\na = 1\n", "拒绝时不能有任何写入"

    @pytest.mark.asyncio
    async def test_delete_refuses_directory(self, ws):
        from app.agent.tools.files import delete_file

        out = await delete_file.ainvoke({"path": "app"})
        assert "拒绝删除目录" in out
        assert (ws.root / "app").is_dir()


# ==================== Shell ====================


class TestShellTool:
    @pytest.mark.asyncio
    async def test_runs_simple_command(self, ws):
        from app.agent.tools.shell import run_command

        out = await run_command.ainvoke({"command": "echo hello-agent"})
        assert "hello-agent" in out and "成功" in out

    @pytest.mark.asyncio
    async def test_no_shell_interpretation(self, ws):
        """不经过 shell：`;` `&&` `|` `$()` 都不该被解释成控制符。

        这是最重要的一条——shell=True 的话，模型只要产出一个带分号的
        字符串就能绕开任何命令白名单。
        """
        from app.agent.tools.shell import run_command

        marker = ws.root / "pwned.txt"
        out = await run_command.ainvoke({"command": f"echo safe; touch {marker}"})
        assert not marker.exists(), "分号后的命令被执行了——说明走了 shell 解释器"
        # 分号连同后面的内容应当只是 echo 的字面参数
        assert "safe" in out

    @pytest.mark.asyncio
    async def test_denies_dangerous_commands(self, ws):
        from app.agent.tools.shell import run_command

        for cmd in ["sudo rm -rf /", "shutdown -h now", "rm -rf /", "rm -rf ."]:
            out = await run_command.ainvoke({"command": cmd})
            assert "拒绝" in out, f"危险命令未被拦截：{cmd}"

    @pytest.mark.asyncio
    async def test_cwd_confined_to_workspace(self, ws):
        from app.agent.tools.shell import run_command

        out = await run_command.ainvoke({"command": "pwd", "cwd": "../.."})
        assert "错误" in out and "工作区外" in out

    @pytest.mark.asyncio
    async def test_falls_back_when_loop_lacks_subprocess(self, ws, monkeypatch):
        """回归：Windows 服务端为兼容 psycopg 用 SelectorEventLoop，它不支持 asyncio 子进程
        （create_subprocess_exec 抛 NotImplementedError）。shell 工具必须退到线程执行，
        而不是让编码 Agent 在 Windows 上整个跑不了命令。"""
        import asyncio

        from app.agent.tools.shell import run_command

        async def _unsupported(*args, **kwargs):
            raise NotImplementedError

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _unsupported)
        out = await run_command.ainvoke({"command": "echo via-thread"})
        assert "via-thread" in out and "成功" in out

        out = await run_command.ainvoke({"command": "definitely-not-a-real-binary-xyz"})
        assert "找不到命令" in out

    @pytest.mark.asyncio
    async def test_thread_fallback_enforces_timeout(self, ws, monkeypatch):
        import asyncio

        import app.core.config as cfg
        from app.agent.tools.shell import run_command

        async def _unsupported(*args, **kwargs):
            raise NotImplementedError

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _unsupported)
        monkeypatch.setattr(cfg.get_settings(), "shell_timeout_seconds", 0.5)
        out = await run_command.ainvoke({"command": "sleep 5"})
        assert "超时" in out


# ==================== 审批闸门 ====================


class TestApprovalPolicy:
    """执行前要不要问用户，是这套工具能不能发布的关键。"""

    def _set_mode(self, mode: str):
        from app.core.config import get_settings

        s = get_settings()
        old = s.tool_approval_mode
        s.tool_approval_mode = mode
        return s, old

    def test_gated_asks_for_write_and_exec_only(self, ws):
        from app.agent.registry import ToolRisk, register_tools
        from app.agent.tools.files import READ_TOOLS, WRITE_TOOLS
        from app.agent.tools.shell import SHELL_TOOLS
        from app.agent.nodes.tools_node import needs_approval

        register_tools(READ_TOOLS, ToolRisk.READ)
        register_tools(WRITE_TOOLS, ToolRisk.WRITE)
        register_tools(SHELL_TOOLS, ToolRisk.EXEC)

        s, old = self._set_mode("gated")
        try:
            assert not needs_approval("read_file"), "只读工具不该打扰用户"
            assert not needs_approval("grep_files")
            assert needs_approval("write_file"), "写文件必须经用户确认"
            assert needs_approval("delete_file")
            assert needs_approval("run_command"), "执行命令必须经用户确认"
        finally:
            s.tool_approval_mode = old

    def test_unknown_tool_defaults_to_requiring_approval(self, ws):
        """保守默认：没分级的工具（比如 MCP 发现来的第三方工具）一律要问。"""
        from app.agent.nodes.tools_node import needs_approval
        from app.agent.registry import ToolRisk, get_risk

        s, old = self._set_mode("gated")
        try:
            assert get_risk("some_unregistered_mcp_tool") is ToolRisk.EXEC
            assert needs_approval("some_unregistered_mcp_tool")
        finally:
            s.tool_approval_mode = old

    def test_readonly_mode_denies_writes(self, ws):
        from app.agent.nodes.tools_node import _denied_by_policy

        s, old = self._set_mode("readonly")
        try:
            assert _denied_by_policy("read_file") is None
            assert _denied_by_policy("write_file") is not None
            assert _denied_by_policy("run_command") is not None
        finally:
            s.tool_approval_mode = old

    def test_auto_mode_asks_nothing(self, ws):
        from app.agent.nodes.tools_node import needs_approval

        s, old = self._set_mode("auto")
        try:
            assert not needs_approval("run_command")
        finally:
            s.tool_approval_mode = old

    @pytest.mark.parametrize(
        "decision,expected",
        [
            (True, True), (False, False),
            ("approve", True), ("yes", True), ("no", False),
            ({"approved": True}, True), ({"approved": False, "reason": "太危险"}, False),
            (None, False), (123, False), ([], False),   # 无法识别 → 必须按拒绝
        ],
    )
    def test_decision_parsing_fails_closed(self, decision, expected):
        """审批结果解析必须 fail-closed：识别不了就当拒绝。

        反过来（识别不了当同意）意味着一个格式错误的回包就能静默执行 rm。
        """
        from app.agent.nodes.tools_node import _parse_decision

        approved, _reason = _parse_decision(decision)
        assert approved is expected
