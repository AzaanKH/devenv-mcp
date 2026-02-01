"""
Tests for health and monitoring tools.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from devenv_mcp.tools.health import (
    ComponentHealth,
    HealthReport,
    DiskUsage,
    ResourceUsage,
    CleanupResult,
    DISK_WARNING_PERCENT,
    DISK_CRITICAL_PERCENT,
    MEMORY_WARNING_PERCENT,
    MEMORY_CRITICAL_PERCENT,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_ctx():
    """Create a mock MCP context."""
    ctx = MagicMock()
    ctx.info = AsyncMock()
    ctx.error = AsyncMock()
    ctx.warning = AsyncMock()
    ctx.report_progress = AsyncMock()

    # Mock elicit for confirmation dialogs
    elicit_result = MagicMock()
    elicit_result.action = "accept"
    elicit_result.data = MagicMock()
    elicit_result.data.confirm = True
    ctx.elicit = AsyncMock(return_value=elicit_result)

    # Mock app context
    app_ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx

    return ctx


@pytest.fixture
def mock_docker_client():
    """Create a mock Docker client."""
    client = MagicMock()
    client.ping = MagicMock(return_value=True)
    client.info = MagicMock(return_value={"ContainersRunning": 3})

    # Mock prune methods
    client.containers.prune = MagicMock(return_value={
        "ContainersDeleted": ["container1", "container2"],
        "SpaceReclaimed": 1024 * 1024 * 100,  # 100MB
    })
    client.images.prune = MagicMock(return_value={
        "ImagesDeleted": ["image1"],
        "SpaceReclaimed": 1024 * 1024 * 500,  # 500MB
    })
    client.networks.prune = MagicMock(return_value={
        "NetworksDeleted": ["network1", "network2", "network3"],
    })
    client.volumes.prune = MagicMock(return_value={
        "VolumesDeleted": ["volume1"],
        "SpaceReclaimed": 1024 * 1024 * 200,  # 200MB
    })

    return client


# =============================================================================
# Model Tests
# =============================================================================


class TestModels:
    """Test Pydantic models for health tools."""

    def test_component_health_model(self):
        """Test ComponentHealth model."""
        health = ComponentHealth(
            name="Docker",
            status="healthy",
            message="Docker is running",
        )
        assert health.name == "Docker"
        assert health.status == "healthy"
        assert health.message == "Docker is running"

    def test_health_report_model(self):
        """Test HealthReport model."""
        report = HealthReport(
            overall_status="healthy",
            components=[
                ComponentHealth(name="Docker", status="healthy", message="OK"),
                ComponentHealth(name="Memory", status="healthy", message="OK"),
            ],
            summary="2/2 components healthy",
        )
        assert report.overall_status == "healthy"
        assert len(report.components) == 2
        assert "2/2" in report.summary

    def test_disk_usage_model(self):
        """Test DiskUsage model."""
        usage = DiskUsage(
            path="/",
            total_gb=500.0,
            used_gb=250.0,
            free_gb=250.0,
            percent_used=50.0,
        )
        assert usage.path == "/"
        assert usage.total_gb == 500.0
        assert usage.percent_used == 50.0

    def test_resource_usage_model(self):
        """Test ResourceUsage model."""
        usage = ResourceUsage(
            cpu_percent=25.5,
            cpu_count=8,
            memory_total_gb=32.0,
            memory_used_gb=16.0,
            memory_percent=50.0,
            disk_usage=[
                DiskUsage(path="/", total_gb=500.0, used_gb=250.0, free_gb=250.0, percent_used=50.0),
            ],
            load_average=[1.5, 2.0, 1.8],
        )
        assert usage.cpu_percent == 25.5
        assert usage.cpu_count == 8
        assert len(usage.disk_usage) == 1
        assert usage.load_average == [1.5, 2.0, 1.8]

    def test_resource_usage_model_no_load_average(self):
        """Test ResourceUsage model without load average (Windows)."""
        usage = ResourceUsage(
            cpu_percent=25.5,
            cpu_count=8,
            memory_total_gb=32.0,
            memory_used_gb=16.0,
            memory_percent=50.0,
            disk_usage=[],
            load_average=None,
        )
        assert usage.load_average is None

    def test_cleanup_result_model(self):
        """Test CleanupResult model."""
        result = CleanupResult(
            success=True,
            space_reclaimed_mb=100.5,
            items_removed={"containers": 2, "images": 5},
            message="Cleanup complete",
        )
        assert result.success is True
        assert result.space_reclaimed_mb == 100.5
        assert result.items_removed["containers"] == 2


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Test threshold constants."""

    def test_disk_thresholds(self):
        """Test disk warning/critical thresholds."""
        assert DISK_WARNING_PERCENT == 80
        assert DISK_CRITICAL_PERCENT == 95
        assert DISK_WARNING_PERCENT < DISK_CRITICAL_PERCENT

    def test_memory_thresholds(self):
        """Test memory warning/critical thresholds."""
        assert MEMORY_WARNING_PERCENT == 85
        assert MEMORY_CRITICAL_PERCENT == 95
        assert MEMORY_WARNING_PERCENT < MEMORY_CRITICAL_PERCENT


# =============================================================================
# devenv_health_check Tests
# =============================================================================


class TestHealthCheck:
    """Tests for devenv_health_check tool."""

    @pytest.mark.asyncio
    async def test_health_check_all_healthy(self, mock_ctx, mock_docker_client):
        """Test health check with all components healthy."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        # Get the tool function
        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_health_check":
                tool_fn = tool.fn
                break

        assert tool_fn is not None

        # Mock Docker
        mock_ctx.request_context.lifespan_context.docker.require_docker.return_value = (
            mock_docker_client
        )

        # Mock psutil for healthy disk and memory
        with patch("devenv_mcp.tools.health.psutil") as mock_psutil:
            # Healthy disk (50% used)
            mock_disk = MagicMock()
            mock_disk.percent = 50.0
            mock_disk.free = 250 * 1024**3  # 250GB free
            mock_psutil.disk_usage.return_value = mock_disk

            # Healthy memory (40% used)
            mock_mem = MagicMock()
            mock_mem.percent = 40.0
            mock_mem.available = 20 * 1024**3  # 20GB available
            mock_psutil.virtual_memory.return_value = mock_mem

            result = await tool_fn(ctx=mock_ctx)

        assert isinstance(result, HealthReport)
        assert result.overall_status == "healthy"
        assert len(result.components) == 3  # Docker, Disk, Memory
        assert all(c.status == "healthy" for c in result.components)

    @pytest.mark.asyncio
    async def test_health_check_docker_unavailable(self, mock_ctx):
        """Test health check when Docker is unavailable."""
        from devenv_mcp.tools.health import register
        from devenv_mcp.utils import DockerUnavailableError
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_health_check":
                tool_fn = tool.fn
                break

        # Mock Docker unavailable
        mock_ctx.request_context.lifespan_context.docker.require_docker.side_effect = (
            DockerUnavailableError("Docker not running")
        )

        with patch("devenv_mcp.tools.health.psutil") as mock_psutil:
            mock_disk = MagicMock()
            mock_disk.percent = 50.0
            mock_disk.free = 250 * 1024**3
            mock_psutil.disk_usage.return_value = mock_disk

            mock_mem = MagicMock()
            mock_mem.percent = 40.0
            mock_mem.available = 20 * 1024**3
            mock_psutil.virtual_memory.return_value = mock_mem

            result = await tool_fn(ctx=mock_ctx)

        assert result.overall_status == "unhealthy"
        docker_component = next(c for c in result.components if c.name == "Docker")
        assert docker_component.status == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_check_disk_critical(self, mock_ctx, mock_docker_client):
        """Test health check with critical disk usage."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_health_check":
                tool_fn = tool.fn
                break

        mock_ctx.request_context.lifespan_context.docker.require_docker.return_value = (
            mock_docker_client
        )

        with patch("devenv_mcp.tools.health.psutil") as mock_psutil:
            # Critical disk (96% used)
            mock_disk = MagicMock()
            mock_disk.percent = 96.0
            mock_disk.free = 20 * 1024**3  # 20GB free
            mock_psutil.disk_usage.return_value = mock_disk

            mock_mem = MagicMock()
            mock_mem.percent = 40.0
            mock_mem.available = 20 * 1024**3
            mock_psutil.virtual_memory.return_value = mock_mem

            result = await tool_fn(ctx=mock_ctx)

        assert result.overall_status == "unhealthy"
        disk_component = next(c for c in result.components if c.name == "Disk Space")
        assert disk_component.status == "unhealthy"
        assert "Critical" in disk_component.message

    @pytest.mark.asyncio
    async def test_health_check_memory_warning(self, mock_ctx, mock_docker_client):
        """Test health check with memory warning."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_health_check":
                tool_fn = tool.fn
                break

        mock_ctx.request_context.lifespan_context.docker.require_docker.return_value = (
            mock_docker_client
        )

        with patch("devenv_mcp.tools.health.psutil") as mock_psutil:
            mock_disk = MagicMock()
            mock_disk.percent = 50.0
            mock_disk.free = 250 * 1024**3
            mock_psutil.disk_usage.return_value = mock_disk

            # Memory warning (88% used)
            mock_mem = MagicMock()
            mock_mem.percent = 88.0
            mock_mem.available = 4 * 1024**3  # 4GB available
            mock_psutil.virtual_memory.return_value = mock_mem

            result = await tool_fn(ctx=mock_ctx)

        assert result.overall_status == "degraded"
        mem_component = next(c for c in result.components if c.name == "Memory")
        assert mem_component.status == "degraded"
        assert "Warning" in mem_component.message


# =============================================================================
# devenv_resource_usage Tests
# =============================================================================


class TestResourceUsage:
    """Tests for devenv_resource_usage tool."""

    @pytest.mark.asyncio
    async def test_resource_usage_basic(self, mock_ctx):
        """Test basic resource usage retrieval."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_resource_usage":
                tool_fn = tool.fn
                break

        assert tool_fn is not None

        with patch("devenv_mcp.tools.health.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 35.5
            mock_psutil.cpu_count.return_value = 8

            mock_mem = MagicMock()
            mock_mem.total = 32 * 1024**3
            mock_mem.used = 16 * 1024**3
            mock_mem.percent = 50.0
            mock_psutil.virtual_memory.return_value = mock_mem

            # Mock disk partitions
            mock_partition = MagicMock()
            mock_partition.device = "/dev/sda1"
            mock_partition.mountpoint = "/"
            mock_partition.fstype = "ext4"
            mock_psutil.disk_partitions.return_value = [mock_partition]

            mock_disk = MagicMock()
            mock_disk.total = 500 * 1024**3
            mock_disk.used = 250 * 1024**3
            mock_disk.free = 250 * 1024**3
            mock_disk.percent = 50.0
            mock_psutil.disk_usage.return_value = mock_disk

            # Mock load average (Unix)
            mock_psutil.getloadavg.return_value = (1.5, 2.0, 1.8)

            result = await tool_fn(ctx=mock_ctx)

        assert isinstance(result, ResourceUsage)
        assert result.cpu_percent == 35.5
        assert result.cpu_count == 8
        assert result.memory_total_gb == 32.0
        assert result.memory_used_gb == 16.0
        assert result.memory_percent == 50.0
        assert len(result.disk_usage) == 1
        assert result.load_average == [1.5, 2.0, 1.8]

    @pytest.mark.asyncio
    async def test_resource_usage_windows_no_load_average(self, mock_ctx):
        """Test resource usage on Windows (no load average)."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_resource_usage":
                tool_fn = tool.fn
                break

        with patch("devenv_mcp.tools.health.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 25.0
            mock_psutil.cpu_count.return_value = 4

            mock_mem = MagicMock()
            mock_mem.total = 16 * 1024**3
            mock_mem.used = 8 * 1024**3
            mock_mem.percent = 50.0
            mock_psutil.virtual_memory.return_value = mock_mem

            mock_psutil.disk_partitions.return_value = []

            # Windows doesn't have getloadavg
            mock_psutil.getloadavg.side_effect = AttributeError("Not available on Windows")

            result = await tool_fn(ctx=mock_ctx)

        assert result.load_average is None

    @pytest.mark.asyncio
    async def test_resource_usage_skips_special_filesystems(self, mock_ctx):
        """Test that special filesystems are skipped."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_resource_usage":
                tool_fn = tool.fn
                break

        with patch("devenv_mcp.tools.health.psutil") as mock_psutil:
            mock_psutil.cpu_percent.return_value = 25.0
            mock_psutil.cpu_count.return_value = 4

            mock_mem = MagicMock()
            mock_mem.total = 16 * 1024**3
            mock_mem.used = 8 * 1024**3
            mock_mem.percent = 50.0
            mock_psutil.virtual_memory.return_value = mock_mem

            # Mix of regular and special filesystems
            partitions = []
            for device, mount, fstype in [
                ("/dev/sda1", "/", "ext4"),
                ("tmpfs", "/tmp", "tmpfs"),
                ("squashfs", "/snap/core", "squashfs"),
            ]:
                p = MagicMock()
                p.device = device
                p.mountpoint = mount
                p.fstype = fstype
                partitions.append(p)

            mock_psutil.disk_partitions.return_value = partitions

            mock_disk = MagicMock()
            mock_disk.total = 500 * 1024**3
            mock_disk.used = 250 * 1024**3
            mock_disk.free = 250 * 1024**3
            mock_disk.percent = 50.0
            mock_psutil.disk_usage.return_value = mock_disk

            mock_psutil.getloadavg.side_effect = AttributeError()

            result = await tool_fn(ctx=mock_ctx)

        # Only the ext4 partition should be included
        assert len(result.disk_usage) == 1
        assert result.disk_usage[0].path == "/"


# =============================================================================
# devenv_cleanup Tests
# =============================================================================


class TestCleanup:
    """Tests for devenv_cleanup tool."""

    @pytest.mark.asyncio
    async def test_cleanup_default_options(self, mock_ctx, mock_docker_client):
        """Test cleanup with default options."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_cleanup":
                tool_fn = tool.fn
                break

        assert tool_fn is not None

        mock_ctx.request_context.lifespan_context.docker.require_docker.return_value = (
            mock_docker_client
        )

        result = await tool_fn(ctx=mock_ctx)

        assert isinstance(result, CleanupResult)
        assert result.success is True
        assert result.items_removed["containers"] == 2
        assert result.items_removed["images"] == 1
        assert result.items_removed["networks"] == 3
        assert "volumes" not in result.items_removed  # Disabled by default
        assert result.space_reclaimed_mb > 0

    @pytest.mark.asyncio
    async def test_cleanup_with_volumes(self, mock_ctx, mock_docker_client):
        """Test cleanup including volumes."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_cleanup":
                tool_fn = tool.fn
                break

        mock_ctx.request_context.lifespan_context.docker.require_docker.return_value = (
            mock_docker_client
        )

        result = await tool_fn(prune_volumes=True, ctx=mock_ctx)

        assert result.success is True
        assert result.items_removed["volumes"] == 1

    @pytest.mark.asyncio
    async def test_cleanup_cancelled(self, mock_ctx, mock_docker_client):
        """Test cleanup when user cancels confirmation."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_cleanup":
                tool_fn = tool.fn
                break

        mock_ctx.request_context.lifespan_context.docker.require_docker.return_value = (
            mock_docker_client
        )

        # User cancels
        elicit_result = MagicMock()
        elicit_result.action = "reject"
        elicit_result.data = None
        mock_ctx.elicit = AsyncMock(return_value=elicit_result)

        result = await tool_fn(ctx=mock_ctx)

        assert result.success is False
        assert "cancelled" in result.message.lower()

    @pytest.mark.asyncio
    async def test_cleanup_docker_unavailable(self, mock_ctx):
        """Test cleanup when Docker is unavailable."""
        from devenv_mcp.tools.health import register
        from devenv_mcp.utils import DockerUnavailableError
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_cleanup":
                tool_fn = tool.fn
                break

        mock_ctx.request_context.lifespan_context.docker.require_docker.side_effect = (
            DockerUnavailableError("Docker not running")
        )

        result = await tool_fn(ctx=mock_ctx)

        assert result.success is False
        assert "not available" in result.message.lower()

    @pytest.mark.asyncio
    async def test_cleanup_nothing_to_clean(self, mock_ctx, mock_docker_client):
        """Test cleanup with all options disabled."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_cleanup":
                tool_fn = tool.fn
                break

        mock_ctx.request_context.lifespan_context.docker.require_docker.return_value = (
            mock_docker_client
        )

        result = await tool_fn(
            prune_containers=False,
            prune_images=False,
            prune_networks=False,
            prune_volumes=False,
            ctx=mock_ctx,
        )

        assert result.success is True
        assert "Nothing to clean up" in result.message

    @pytest.mark.asyncio
    async def test_cleanup_partial_failure(self, mock_ctx, mock_docker_client):
        """Test cleanup with partial failure."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_cleanup":
                tool_fn = tool.fn
                break

        mock_ctx.request_context.lifespan_context.docker.require_docker.return_value = (
            mock_docker_client
        )

        # Containers prune works, images prune fails
        mock_docker_client.images.prune.side_effect = Exception("Image prune failed")

        result = await tool_fn(ctx=mock_ctx)

        assert result.success is False
        assert "partially failed" in result.message.lower()
        assert result.items_removed["containers"] == 2  # This succeeded


# =============================================================================
# Integration Tests
# =============================================================================


@pytest.mark.integration
class TestHealthIntegration:
    """Integration tests for health tools (require real system access)."""

    @pytest.mark.asyncio
    async def test_resource_usage_real(self, mock_ctx):
        """Test resource usage with real psutil (no mocking)."""
        from devenv_mcp.tools.health import register
        from mcp.server.fastmcp import FastMCP

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for name, tool in mcp._tool_manager._tools.items():
            if name == "devenv_resource_usage":
                tool_fn = tool.fn
                break

        result = await tool_fn(ctx=mock_ctx)

        assert isinstance(result, ResourceUsage)
        assert 0 <= result.cpu_percent <= 100
        assert result.cpu_count > 0
        assert result.memory_total_gb > 0
        assert result.memory_used_gb > 0
        assert 0 <= result.memory_percent <= 100
