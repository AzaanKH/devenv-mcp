"""
Unit tests for Docker tools.

These tests use mocked Docker client - no real Docker required.
Run with: uv run pytest tests/test_docker.py -v

For integration tests with real Docker:
    uv run pytest tests/test_docker.py -v --integration
"""

import pytest

from devenv_mcp.tools.docker import ContainerInfo, ContainerLogs, ComposeStatus


# =============================================================================
# Unit Tests (Mocked Docker)
# =============================================================================

class TestListContainers:
    """Tests for devenv_docker_list_containers."""
    
    @pytest.mark.asyncio
    async def test_list_running_containers(self, mock_mcp_context, mock_container):
        """Test listing running containers."""
        # Import after fixtures are set up
        from devenv_mcp.tools import docker as docker_tools
        from mcp.server.fastmcp import FastMCP
        
        # Create a test MCP instance
        mcp = FastMCP("test")
        docker_tools.register(mcp)
        
        # Get the registered tool function
        # The tool is registered as 'devenv_docker_list_containers'
        tool_func = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_docker_list_containers":
                tool_func = tool.fn
                break
        
        assert tool_func is not None, "Tool not found"
        
        # Call the tool with mock context
        result = await tool_func(all=False, ctx=mock_mcp_context)
        
        # Verify result
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].name == "test-container"
        assert result[0].status == "running"
    
    @pytest.mark.asyncio
    async def test_list_containers_docker_unavailable(self, mock_mcp_context):
        """Test graceful handling when Docker is unavailable."""
        from devenv_mcp.tools import docker as docker_tools
        from devenv_mcp.utils.docker_client import DockerUnavailableError
        from mcp.server.fastmcp import FastMCP
        
        # Make Docker unavailable
        mock_mcp_context.request_context.lifespan_context.docker._is_available = False
        mock_mcp_context.request_context.lifespan_context.docker._client = None
        
        mcp = FastMCP("test")
        docker_tools.register(mcp)
        
        tool_func = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_docker_list_containers":
                tool_func = tool.fn
                break
        
        result = await tool_func(all=False, ctx=mock_mcp_context)
        
        # Should return empty list, not raise exception
        assert result == []


class TestStartContainer:
    """Tests for devenv_docker_start_container."""
    
    @pytest.mark.asyncio
    async def test_start_stopped_container(self, mock_mcp_context, mock_container):
        """Test starting a stopped container."""
        from devenv_mcp.tools import docker as docker_tools
        from mcp.server.fastmcp import FastMCP
        
        # Set container as stopped
        mock_container.status = "exited"
        
        mcp = FastMCP("test")
        docker_tools.register(mcp)
        
        tool_func = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_docker_start_container":
                tool_func = tool.fn
                break
        
        result = await tool_func(container_id="test-container", ctx=mock_mcp_context)
        
        assert "Successfully started" in result
        mock_container.start.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_start_already_running(self, mock_mcp_context, mock_container):
        """Test starting an already running container."""
        from devenv_mcp.tools import docker as docker_tools
        from mcp.server.fastmcp import FastMCP
        
        mock_container.status = "running"
        
        mcp = FastMCP("test")
        docker_tools.register(mcp)
        
        tool_func = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_docker_start_container":
                tool_func = tool.fn
                break
        
        result = await tool_func(container_id="test-container", ctx=mock_mcp_context)
        
        assert "already running" in result
        mock_container.start.assert_not_called()


class TestStopContainer:
    """Tests for devenv_docker_stop_container."""
    
    @pytest.mark.asyncio
    async def test_stop_running_container(self, mock_mcp_context, mock_container):
        """Test stopping a running container."""
        from devenv_mcp.tools import docker as docker_tools
        from mcp.server.fastmcp import FastMCP
        
        mock_container.status = "running"
        
        mcp = FastMCP("test")
        docker_tools.register(mcp)
        
        tool_func = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_docker_stop_container":
                tool_func = tool.fn
                break
        
        result = await tool_func(container_id="test-container", ctx=mock_mcp_context)
        
        assert "Successfully stopped" in result
        mock_container.stop.assert_called_once()


class TestContainerLogs:
    """Tests for devenv_docker_logs."""
    
    @pytest.mark.asyncio
    async def test_get_logs(self, mock_mcp_context, mock_container):
        """Test getting container logs."""
        from devenv_mcp.tools import docker as docker_tools
        from mcp.server.fastmcp import FastMCP
        
        mcp = FastMCP("test")
        docker_tools.register(mcp)
        
        tool_func = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_docker_logs":
                tool_func = tool.fn
                break
        
        result = await tool_func(container_id="test-container", tail=100, ctx=mock_mcp_context)
        
        assert isinstance(result, ContainerLogs)
        assert result.container_name == "test-container"
        assert "Test log line" in result.logs


class TestDockerCompose:
    """Tests for Docker Compose tools."""
    
    @pytest.mark.asyncio
    async def test_compose_up(self, mock_mcp_context, mock_run_docker_compose, tmp_path):
        """Test docker compose up."""
        from devenv_mcp.tools import docker as docker_tools
        from mcp.server.fastmcp import FastMCP
        
        # Create a fake compose file
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text("version: '3'\nservices:\n  web:\n    image: nginx")
        
        mcp = FastMCP("test")
        docker_tools.register(mcp)
        
        tool_func = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_docker_compose_up":
                tool_func = tool.fn
                break
        
        result = await tool_func(
            working_dir=str(tmp_path),
            compose_file="docker-compose.yml",
            ctx=mock_mcp_context,
        )
        
        assert isinstance(result, ComposeStatus)
        assert result.compose_file == "docker-compose.yml"
        assert "Successfully" in result.message or "done" in result.message.lower()


# =============================================================================
# Integration Tests (Real Docker)
# =============================================================================

@pytest.mark.integration
class TestDockerIntegration:
    """Integration tests that require real Docker."""
    
    @pytest.mark.asyncio
    async def test_real_list_containers(self, integration_app_context):
        """Test listing real containers."""
        containers = integration_app_context.docker.list_containers(all=True)
        
        # Just verify it returns a list (might be empty)
        assert isinstance(containers, list)
    
    @pytest.mark.asyncio
    async def test_real_docker_info(self, integration_app_context):
        """Test getting real Docker info."""
        info = integration_app_context.docker.get_info()
        
        assert "Containers" in info
        assert "Images" in info
