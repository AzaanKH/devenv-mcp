"""
System health and monitoring tools for DevEnv MCP.

These tools provide health checks, resource monitoring, and cleanup operations.
All tools are prefixed with `devenv_health_` or `devenv_resource_`.

Implemented tools:
- devenv_health_check [readOnly: true]
- devenv_resource_usage [readOnly: true]
- devenv_cleanup [destructive: true]
"""

from typing import TYPE_CHECKING

import psutil
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pydantic import BaseModel, Field

from devenv_mcp.utils import DockerUnavailableError, get_logger

if TYPE_CHECKING:
    from devenv_mcp.server import AppContext

logger = get_logger("tools.health")


# =============================================================================
# Data Models
# =============================================================================


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    name: str = Field(description="Component name")
    status: str = Field(description="Status: healthy, degraded, unhealthy, unknown")
    message: str = Field(description="Status message or error details")


class HealthReport(BaseModel):
    """Overall health report for the development environment."""

    overall_status: str = Field(description="Overall status: healthy, degraded, unhealthy")
    components: list[ComponentHealth] = Field(description="Individual component statuses")
    summary: str = Field(description="Human-readable summary")


class DiskUsage(BaseModel):
    """Disk usage information for a mount point."""

    path: str = Field(description="Mount point path")
    total_gb: float = Field(description="Total space in GB")
    used_gb: float = Field(description="Used space in GB")
    free_gb: float = Field(description="Free space in GB")
    percent_used: float = Field(description="Percentage of space used")


class ResourceUsage(BaseModel):
    """System resource usage statistics."""

    cpu_percent: float = Field(description="Current CPU usage percentage")
    cpu_count: int = Field(description="Number of CPU cores")
    memory_total_gb: float = Field(description="Total RAM in GB")
    memory_used_gb: float = Field(description="Used RAM in GB")
    memory_percent: float = Field(description="RAM usage percentage")
    disk_usage: list[DiskUsage] = Field(description="Disk usage per mount point")
    load_average: list[float] | None = Field(
        description="Load average (1, 5, 15 min) - Unix only"
    )


class CleanupResult(BaseModel):
    """Result of a cleanup operation."""

    success: bool = Field(description="Whether cleanup succeeded")
    space_reclaimed_mb: float = Field(description="Space reclaimed in MB")
    items_removed: dict[str, int] = Field(
        description="Count of items removed by type (containers, images, etc.)"
    )
    message: str = Field(description="Summary message")


# =============================================================================
# Constants
# =============================================================================

# Disk usage thresholds
DISK_WARNING_PERCENT = 80
DISK_CRITICAL_PERCENT = 95

# Memory thresholds
MEMORY_WARNING_PERCENT = 85
MEMORY_CRITICAL_PERCENT = 95


# =============================================================================
# Tool Registration
# =============================================================================


def register(mcp: FastMCP):
    """Register all health/monitoring tools with the MCP server."""

    # =========================================================================
    # devenv_health_check - Check overall system health
    # [readOnly: true]
    # =========================================================================
    @mcp.tool()
    async def devenv_health_check(
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> HealthReport:
        """
        Run a comprehensive health check on the development environment.

        Checks:
        - Docker availability and status
        - Disk space on main drives
        - Memory availability
        - Common development ports

        Returns:
            HealthReport with overall status and individual component statuses

        Example:
            devenv_health_check()
        """
        app_ctx = ctx.request_context.lifespan_context
        components = []

        # Check Docker
        docker_status = "healthy"
        docker_msg = "Docker is running"
        try:
            docker_client = app_ctx.docker.require_docker()
            docker_client.ping()
            info = docker_client.info()
            containers_running = info.get("ContainersRunning", 0)
            docker_msg = f"Docker is running ({containers_running} container(s) active)"
        except DockerUnavailableError as e:
            docker_status = "unhealthy"
            docker_msg = str(e)
        except Exception as e:
            docker_status = "unhealthy"
            docker_msg = f"Docker error: {e}"

        components.append(ComponentHealth(
            name="Docker",
            status=docker_status,
            message=docker_msg,
        ))

        # Check disk space
        try:
            disk = psutil.disk_usage("/")
            percent = disk.percent
            free_gb = disk.free / (1024 ** 3)

            if percent >= DISK_CRITICAL_PERCENT:
                disk_status = "unhealthy"
                disk_msg = f"Critical: {percent:.1f}% used, {free_gb:.1f}GB free"
            elif percent >= DISK_WARNING_PERCENT:
                disk_status = "degraded"
                disk_msg = f"Warning: {percent:.1f}% used, {free_gb:.1f}GB free"
            else:
                disk_status = "healthy"
                disk_msg = f"{percent:.1f}% used, {free_gb:.1f}GB free"
        except Exception as e:
            disk_status = "unknown"
            disk_msg = f"Could not check disk: {e}"

        components.append(ComponentHealth(
            name="Disk Space",
            status=disk_status,
            message=disk_msg,
        ))

        # Check memory
        try:
            mem = psutil.virtual_memory()
            percent = mem.percent
            available_gb = mem.available / (1024 ** 3)

            if percent >= MEMORY_CRITICAL_PERCENT:
                mem_status = "unhealthy"
                mem_msg = f"Critical: {percent:.1f}% used, {available_gb:.1f}GB available"
            elif percent >= MEMORY_WARNING_PERCENT:
                mem_status = "degraded"
                mem_msg = f"Warning: {percent:.1f}% used, {available_gb:.1f}GB available"
            else:
                mem_status = "healthy"
                mem_msg = f"{percent:.1f}% used, {available_gb:.1f}GB available"
        except Exception as e:
            mem_status = "unknown"
            mem_msg = f"Could not check memory: {e}"

        components.append(ComponentHealth(
            name="Memory",
            status=mem_status,
            message=mem_msg,
        ))

        # Determine overall status
        statuses = [c.status for c in components]
        if "unhealthy" in statuses:
            overall = "unhealthy"
        elif "degraded" in statuses:
            overall = "degraded"
        elif "unknown" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"

        # Build summary
        healthy_count = sum(1 for s in statuses if s == "healthy")
        summary = f"{healthy_count}/{len(components)} components healthy"
        if overall != "healthy":
            unhealthy = [c.name for c in components if c.status in ("unhealthy", "degraded")]
            summary += f" - issues: {', '.join(unhealthy)}"

        await ctx.info(f"Health check complete: {overall}")

        return HealthReport(
            overall_status=overall,
            components=components,
            summary=summary,
        )

    # =========================================================================
    # devenv_resource_usage - Get system resource usage
    # [readOnly: true]
    # =========================================================================
    @mcp.tool()
    async def devenv_resource_usage(
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> ResourceUsage:
        """
        Get current system resource usage statistics.

        Returns CPU, memory, and disk usage information useful for diagnosing
        performance issues or deciding when to clean up resources.

        Returns:
            ResourceUsage with CPU, memory, disk stats

        Example:
            devenv_resource_usage()
        """
        # CPU info
        cpu_percent = psutil.cpu_percent(interval=0.5)
        cpu_count = psutil.cpu_count()

        # Memory info
        mem = psutil.virtual_memory()
        memory_total_gb = round(mem.total / (1024 ** 3), 2)
        memory_used_gb = round(mem.used / (1024 ** 3), 2)
        memory_percent = mem.percent

        # Disk info - get all partitions
        disk_usage = []
        partitions = psutil.disk_partitions()
        seen_devices = set()

        for partition in partitions:
            # Skip duplicate devices and special filesystems
            if partition.device in seen_devices:
                continue
            if partition.fstype in ("squashfs", "tmpfs", "devtmpfs"):
                continue
            seen_devices.add(partition.device)

            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disk_usage.append(DiskUsage(
                    path=partition.mountpoint,
                    total_gb=round(usage.total / (1024 ** 3), 2),
                    used_gb=round(usage.used / (1024 ** 3), 2),
                    free_gb=round(usage.free / (1024 ** 3), 2),
                    percent_used=usage.percent,
                ))
            except (PermissionError, OSError):
                # Skip partitions we can't access
                continue

        # Load average (Unix only)
        load_average = None
        try:
            load_average = list(psutil.getloadavg())
        except (AttributeError, OSError):
            # Not available on Windows
            pass

        await ctx.info(f"Resource usage: CPU {cpu_percent}%, Memory {memory_percent}%")

        return ResourceUsage(
            cpu_percent=cpu_percent,
            cpu_count=cpu_count,
            memory_total_gb=memory_total_gb,
            memory_used_gb=memory_used_gb,
            memory_percent=memory_percent,
            disk_usage=disk_usage,
            load_average=load_average,
        )

    # =========================================================================
    # devenv_cleanup - Clean up unused Docker resources
    # [destructive: true] - Requires confirmation
    # =========================================================================
    @mcp.tool()
    async def devenv_cleanup(
        prune_containers: bool = True,
        prune_images: bool = True,
        prune_networks: bool = True,
        prune_volumes: bool = False,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> CleanupResult:
        """
        Clean up unused Docker resources to free disk space.

        By default, removes stopped containers, dangling images, and unused networks.
        Volume pruning is disabled by default to prevent data loss.

        Args:
            prune_containers: Remove stopped containers (default: True)
            prune_images: Remove dangling/unused images (default: True)
            prune_networks: Remove unused networks (default: True)
            prune_volumes: Remove unused volumes (default: False - DATA LOSS RISK!)

        Returns:
            CleanupResult with space reclaimed and items removed

        Example:
            - Safe cleanup: devenv_cleanup()
            - Include volumes: devenv_cleanup(prune_volumes=True)

        ⚠️ WARNING: Volume pruning can cause permanent data loss!
        """
        app_ctx = ctx.request_context.lifespan_context

        # Check Docker availability
        try:
            docker_client = app_ctx.docker.require_docker()
        except DockerUnavailableError as e:
            return CleanupResult(
                success=False,
                space_reclaimed_mb=0,
                items_removed={},
                message=f"Docker not available: {e}",
            )

        # Build confirmation message
        actions = []
        if prune_containers:
            actions.append("stopped containers")
        if prune_images:
            actions.append("dangling images")
        if prune_networks:
            actions.append("unused networks")
        if prune_volumes:
            actions.append("unused volumes (DATA LOSS RISK!)")

        if not actions:
            return CleanupResult(
                success=True,
                space_reclaimed_mb=0,
                items_removed={},
                message="Nothing to clean up (all options disabled)",
            )

        # Request confirmation
        from pydantic import BaseModel as ConfirmModel

        class ConfirmCleanup(ConfirmModel):
            confirm: bool = Field(description="Set to true to confirm cleanup")

        confirm_msg = "This will remove:\n"
        for action in actions:
            confirm_msg += f"  - {action}\n"
        if prune_volumes:
            confirm_msg += "\n⚠️ WARNING: Volume pruning will DELETE DATA permanently!"
        confirm_msg += "\n\nProceed with cleanup?"

        result = await ctx.elicit(
            message=confirm_msg,
            schema=ConfirmCleanup,
        )

        if result.action != "accept" or not result.data or not result.data.confirm:
            return CleanupResult(
                success=False,
                space_reclaimed_mb=0,
                items_removed={},
                message="Cleanup cancelled",
            )

        # Perform cleanup
        items_removed = {}
        space_reclaimed = 0

        await ctx.info("Starting Docker cleanup...")

        try:
            # Prune containers
            if prune_containers:
                result = docker_client.containers.prune()
                deleted = result.get("ContainersDeleted") or []
                items_removed["containers"] = len(deleted)
                space_reclaimed += result.get("SpaceReclaimed", 0)
                await ctx.info(f"Removed {len(deleted)} container(s)")

            # Prune images
            if prune_images:
                result = docker_client.images.prune()
                deleted = result.get("ImagesDeleted") or []
                items_removed["images"] = len(deleted)
                space_reclaimed += result.get("SpaceReclaimed", 0)
                await ctx.info(f"Removed {len(deleted)} image(s)")

            # Prune networks
            if prune_networks:
                result = docker_client.networks.prune()
                deleted = result.get("NetworksDeleted") or []
                items_removed["networks"] = len(deleted)
                await ctx.info(f"Removed {len(deleted)} network(s)")

            # Prune volumes (dangerous!)
            if prune_volumes:
                result = docker_client.volumes.prune()
                deleted = result.get("VolumesDeleted") or []
                items_removed["volumes"] = len(deleted)
                space_reclaimed += result.get("SpaceReclaimed", 0)
                await ctx.info(f"Removed {len(deleted)} volume(s)")

        except Exception as e:
            await ctx.error(f"Cleanup error: {e}")
            return CleanupResult(
                success=False,
                space_reclaimed_mb=space_reclaimed / (1024 * 1024),
                items_removed=items_removed,
                message=f"Cleanup partially failed: {e}",
            )

        space_mb = space_reclaimed / (1024 * 1024)
        total_items = sum(items_removed.values())

        await ctx.info(f"Cleanup complete: {total_items} items, {space_mb:.1f}MB reclaimed")

        return CleanupResult(
            success=True,
            space_reclaimed_mb=round(space_mb, 2),
            items_removed=items_removed,
            message=f"Cleanup complete: removed {total_items} item(s), reclaimed {space_mb:.1f}MB",
        )

    logger.info("Health tools registered")
