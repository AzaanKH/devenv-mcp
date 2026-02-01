"""
Tests for process and port management tools.

Tests both unit tests (mocked) and integration tests (real processes).
"""

from unittest.mock import MagicMock, patch

import pytest

from devenv_mcp.tools.process import (
    PortInfo,
    ProcessInfo,
    _find_process_by_port,
    _get_process_info,
    _is_dev_process,
)

# =============================================================================
# Unit Tests - Helper Functions
# =============================================================================


class TestIsDevProcess:
    """Tests for _is_dev_process helper function."""

    def test_recognizes_python(self):
        """Test that python processes are recognized as dev processes."""
        assert _is_dev_process("python") is True
        assert _is_dev_process("python3") is True
        assert _is_dev_process("python.exe") is True
        assert _is_dev_process("Python") is True  # Case insensitive

    def test_recognizes_node(self):
        """Test that node processes are recognized as dev processes."""
        assert _is_dev_process("node") is True
        assert _is_dev_process("node.exe") is True
        assert _is_dev_process("npm") is True

    def test_recognizes_docker(self):
        """Test that docker processes are recognized as dev processes."""
        assert _is_dev_process("docker") is True
        assert _is_dev_process("dockerd") is True

    def test_recognizes_dev_servers(self):
        """Test that common dev servers are recognized."""
        assert _is_dev_process("uvicorn") is True
        assert _is_dev_process("gunicorn") is True
        assert _is_dev_process("vite") is True

    def test_rejects_non_dev_processes(self):
        """Test that non-dev processes are rejected."""
        assert _is_dev_process("svchost") is False
        assert _is_dev_process("explorer") is False
        assert _is_dev_process("systemd") is False

    def test_keyword_matching(self):
        """Test that keyword matching works for variations."""
        assert _is_dev_process("python3.11") is True
        assert _is_dev_process("node-v18") is True


class TestGetProcessInfo:
    """Tests for _get_process_info helper function."""

    def test_extracts_process_info(self):
        """Test extracting info from a mock process."""
        mock_proc = MagicMock()
        mock_proc.pid = 1234
        mock_proc.name.return_value = "python"
        mock_proc.cmdline.return_value = ["python", "app.py"]
        mock_proc.cpu_percent.return_value = 5.5
        mock_proc.memory_info.return_value = MagicMock(rss=100 * 1024 * 1024)  # 100 MB
        mock_proc.status.return_value = "running"
        mock_proc.username.return_value = "testuser"

        # Mock the oneshot context manager
        mock_proc.oneshot.return_value.__enter__ = MagicMock()
        mock_proc.oneshot.return_value.__exit__ = MagicMock()

        result = _get_process_info(mock_proc)

        assert result is not None
        assert result.pid == 1234
        assert result.name == "python"
        assert "python app.py" in result.cmdline
        assert result.cpu_percent == 5.5
        assert result.memory_mb == 100.0
        assert result.status == "running"
        assert result.username == "testuser"

    def test_returns_none_for_inaccessible_process(self):
        """Test that None is returned for processes we can't access."""
        import psutil

        mock_proc = MagicMock()
        mock_proc.oneshot.return_value.__enter__ = MagicMock(
            side_effect=psutil.AccessDenied(pid=1234)
        )

        result = _get_process_info(mock_proc)

        assert result is None


class TestFindProcessByPort:
    """Tests for _find_process_by_port helper function."""

    def test_finds_process_on_port(self):
        """Test finding a process using a specific port."""
        mock_conn = MagicMock()
        mock_conn.laddr = MagicMock(port=8000)
        mock_conn.pid = 1234

        mock_proc = MagicMock()
        mock_proc.name.return_value = "python"

        with patch("devenv_mcp.tools.process.psutil.net_connections", return_value=[mock_conn]):
            with patch("devenv_mcp.tools.process.psutil.Process", return_value=mock_proc):
                pid, name = _find_process_by_port(8000)

        assert pid == 1234
        assert name == "python"

    def test_returns_none_for_unused_port(self):
        """Test that None is returned for ports not in use."""
        with patch("devenv_mcp.tools.process.psutil.net_connections", return_value=[]):
            pid, name = _find_process_by_port(9999)

        assert pid is None
        assert name == ""


# =============================================================================
# Unit Tests - devenv_process_list tool
# =============================================================================


class TestDevenvProcessList:
    """Tests for the devenv_process_list MCP tool."""

    def _get_tool_fn(self, tool_name: str):
        """Helper to get a registered tool function."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.process import register

        mcp = FastMCP("test")
        register(mcp)

        for tool in mcp._tool_manager._tools.values():
            if tool.name == tool_name:
                return tool.fn
        return None

    @pytest.mark.asyncio
    async def test_lists_dev_processes(self, mock_mcp_context):
        """Test listing development processes."""
        tool_fn = self._get_tool_fn("devenv_process_list")
        assert tool_fn is not None

        # Create mock processes
        mock_python = MagicMock()
        mock_python.name.return_value = "python"
        mock_python.pid = 1234

        mock_notepad = MagicMock()
        mock_notepad.name.return_value = "notepad"
        mock_notepad.pid = 5678

        mock_proc_info = ProcessInfo(
            pid=1234,
            name="python",
            cmdline="python app.py",
            cpu_percent=5.0,
            memory_mb=100.0,
            status="running",
            username="testuser",
        )

        with patch("devenv_mcp.tools.process.psutil.process_iter", return_value=[mock_python, mock_notepad]):
            with patch("devenv_mcp.tools.process._get_process_info", return_value=mock_proc_info):
                result = await tool_fn(
                    filter_dev_only=True,
                    name_filter=None,
                    ctx=mock_mcp_context,
                )

        # Should only include python (dev process), not notepad
        assert len(result) >= 1
        assert all(isinstance(p, ProcessInfo) for p in result)

    @pytest.mark.asyncio
    async def test_filters_by_name(self, mock_mcp_context):
        """Test filtering processes by name."""
        tool_fn = self._get_tool_fn("devenv_process_list")

        mock_python = MagicMock()
        mock_python.name.return_value = "python"

        mock_node = MagicMock()
        mock_node.name.return_value = "node"

        mock_proc_info = ProcessInfo(
            pid=1234,
            name="python",
            cmdline="python app.py",
            cpu_percent=5.0,
            memory_mb=100.0,
            status="running",
            username="testuser",
        )

        with patch("devenv_mcp.tools.process.psutil.process_iter", return_value=[mock_python, mock_node]):
            with patch("devenv_mcp.tools.process._get_process_info", return_value=mock_proc_info):
                result = await tool_fn(
                    filter_dev_only=False,
                    name_filter="python",
                    ctx=mock_mcp_context,
                )

        # All results should contain "python" in name
        for proc in result:
            assert "python" in proc.name.lower()


# =============================================================================
# Unit Tests - devenv_port_list tool
# =============================================================================


class TestDevenvPortList:
    """Tests for the devenv_port_list MCP tool."""

    def _get_tool_fn(self, tool_name: str):
        """Helper to get a registered tool function."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.process import register

        mcp = FastMCP("test")
        register(mcp)

        for tool in mcp._tool_manager._tools.values():
            if tool.name == tool_name:
                return tool.fn
        return None

    @pytest.mark.asyncio
    async def test_lists_dev_ports(self, mock_mcp_context):
        """Test listing common development ports."""
        tool_fn = self._get_tool_fn("devenv_port_list")
        assert tool_fn is not None

        # Create mock connections
        mock_conn_8000 = MagicMock()
        mock_conn_8000.laddr = MagicMock(ip="127.0.0.1", port=8000)
        mock_conn_8000.pid = 1234
        mock_conn_8000.status = "LISTEN"
        mock_conn_8000.type = MagicMock(name="SOCK_STREAM")

        mock_conn_random = MagicMock()
        mock_conn_random.laddr = MagicMock(ip="127.0.0.1", port=54321)
        mock_conn_random.pid = 5678
        mock_conn_random.status = "LISTEN"
        mock_conn_random.type = MagicMock(name="SOCK_STREAM")

        mock_proc = MagicMock()
        mock_proc.name.return_value = "python"

        with patch("devenv_mcp.tools.process.psutil.net_connections", return_value=[mock_conn_8000, mock_conn_random]):
            with patch("devenv_mcp.tools.process.psutil.Process", return_value=mock_proc):
                result = await tool_fn(
                    filter_dev_ports=True,
                    port_range=None,
                    ctx=mock_mcp_context,
                )

        # Should only include port 8000 (common dev port), not 54321
        ports = [p.port for p in result]
        assert 8000 in ports
        assert 54321 not in ports

    @pytest.mark.asyncio
    async def test_filters_by_port_range(self, mock_mcp_context):
        """Test filtering ports by range."""
        tool_fn = self._get_tool_fn("devenv_port_list")

        mock_conn_3000 = MagicMock()
        mock_conn_3000.laddr = MagicMock(ip="127.0.0.1", port=3000)
        mock_conn_3000.pid = 1234
        mock_conn_3000.status = "LISTEN"
        mock_conn_3000.type = MagicMock(name="SOCK_STREAM")

        mock_conn_8000 = MagicMock()
        mock_conn_8000.laddr = MagicMock(ip="127.0.0.1", port=8000)
        mock_conn_8000.pid = 5678
        mock_conn_8000.status = "LISTEN"
        mock_conn_8000.type = MagicMock(name="SOCK_STREAM")

        mock_proc = MagicMock()
        mock_proc.name.return_value = "python"

        with patch("devenv_mcp.tools.process.psutil.net_connections", return_value=[mock_conn_3000, mock_conn_8000]):
            with patch("devenv_mcp.tools.process.psutil.Process", return_value=mock_proc):
                result = await tool_fn(
                    filter_dev_ports=False,
                    port_range=(7000, 9000),
                    ctx=mock_mcp_context,
                )

        # Should only include port 8000 (in range), not 3000
        ports = [p.port for p in result]
        assert 8000 in ports
        assert 3000 not in ports


# =============================================================================
# Unit Tests - devenv_port_kill tool
# =============================================================================


class TestDevenvPortKill:
    """Tests for the devenv_port_kill MCP tool."""

    def _get_tool_fn(self, tool_name: str):
        """Helper to get a registered tool function."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.process import register

        mcp = FastMCP("test")
        register(mcp)

        for tool in mcp._tool_manager._tools.values():
            if tool.name == tool_name:
                return tool.fn
        return None

    @pytest.mark.asyncio
    async def test_kills_process_on_port(self, mock_mcp_context):
        """Test killing a process on a specific port."""
        tool_fn = self._get_tool_fn("devenv_port_kill")
        assert tool_fn is not None

        mock_proc = MagicMock()
        mock_proc.name.return_value = "python"
        mock_proc.cmdline.return_value = ["python", "server.py"]
        mock_proc.terminate.return_value = None
        mock_proc.wait.return_value = None

        with patch("devenv_mcp.tools.process._find_process_by_port", return_value=(1234, "python")):
            with patch("devenv_mcp.tools.process.psutil.Process", return_value=mock_proc):
                result = await tool_fn(
                    port=8000,
                    force=False,
                    ctx=mock_mcp_context,
                )

        assert "Successfully killed" in result
        mock_proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_no_process_on_port(self, mock_mcp_context):
        """Test handling when no process is using the port."""
        tool_fn = self._get_tool_fn("devenv_port_kill")

        with patch("devenv_mcp.tools.process._find_process_by_port", return_value=(None, "")):
            result = await tool_fn(
                port=9999,
                force=False,
                ctx=mock_mcp_context,
            )

        assert "No process found" in result

    @pytest.mark.asyncio
    async def test_cancellation_preserves_process(self, mock_mcp_context):
        """Test that cancelling the confirmation preserves the process."""
        tool_fn = self._get_tool_fn("devenv_port_kill")

        # Mock elicit to return cancelled
        async def mock_elicit_cancel(message, schema):
            result = MagicMock()
            result.action = "cancel"
            result.data = None
            return result

        mock_mcp_context.elicit = mock_elicit_cancel

        mock_proc = MagicMock()
        mock_proc.name.return_value = "python"
        mock_proc.cmdline.return_value = ["python", "server.py"]

        with patch("devenv_mcp.tools.process._find_process_by_port", return_value=(1234, "python")):
            with patch("devenv_mcp.tools.process.psutil.Process", return_value=mock_proc):
                result = await tool_fn(
                    port=8000,
                    force=False,
                    ctx=mock_mcp_context,
                )

        assert "cancelled" in result.lower()
        # Process should NOT have been terminated
        mock_proc.terminate.assert_not_called()
        mock_proc.kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_kill_uses_sigkill(self, mock_mcp_context):
        """Test that force=True uses SIGKILL instead of SIGTERM."""
        tool_fn = self._get_tool_fn("devenv_port_kill")

        mock_proc = MagicMock()
        mock_proc.name.return_value = "python"
        mock_proc.cmdline.return_value = ["python", "server.py"]
        mock_proc.kill.return_value = None
        mock_proc.wait.return_value = None

        with patch("devenv_mcp.tools.process._find_process_by_port", return_value=(1234, "python")):
            with patch("devenv_mcp.tools.process.psutil.Process", return_value=mock_proc):
                result = await tool_fn(
                    port=8000,
                    force=True,
                    ctx=mock_mcp_context,
                )

        assert "Successfully killed" in result
        mock_proc.kill.assert_called_once()  # SIGKILL
        mock_proc.terminate.assert_not_called()  # Not SIGTERM


# =============================================================================
# Integration Tests (requires real processes)
# =============================================================================


@pytest.mark.integration
class TestProcessIntegration:
    """Integration tests that examine real processes."""

    @pytest.mark.asyncio
    async def test_lists_real_processes(self, mock_mcp_context):
        """Test listing real processes on the system."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.process import register

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_process_list":
                tool_fn = tool.fn
                break

        # List all processes (not just dev)
        result = await tool_fn(
            filter_dev_only=False,
            name_filter=None,
            ctx=mock_mcp_context,
        )

        # Should find at least some processes
        assert len(result) > 0
        # All should be ProcessInfo
        assert all(isinstance(p, ProcessInfo) for p in result)

    @pytest.mark.asyncio
    async def test_lists_real_ports(self, mock_mcp_context):
        """Test listing real ports on the system."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.process import register

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_port_list":
                tool_fn = tool.fn
                break

        # List all ports (not just dev ports)
        result = await tool_fn(
            filter_dev_ports=False,
            port_range=None,
            ctx=mock_mcp_context,
        )

        # Should return a list (may be empty if no ports in use)
        assert isinstance(result, list)
        # All should be PortInfo
        assert all(isinstance(p, PortInfo) for p in result)
