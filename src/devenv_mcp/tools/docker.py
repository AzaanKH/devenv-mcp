"""
Docker management tools for DevEnv MCP.

These tools provide container, image, and compose management capabilities.
All tools are prefixed with `devenv_docker_` for namespacing.

Tool Annotations:
- readOnly: true - Tool only reads data, no side effects
- destructive: false - Tool makes changes but they're reversible  
- destructive: true - Tool makes irreversible changes (requires confirmation)
"""

from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pydantic import BaseModel, Field

from devenv_mcp.utils import DockerUnavailableError, get_logger, run_docker_compose

if TYPE_CHECKING:
    from devenv_mcp.server import AppContext

logger = get_logger("tools.docker")


# =============================================================================
# Data Models (Pydantic models for structured output)
# =============================================================================

class ContainerInfo(BaseModel):
    """Information about a Docker container."""
    
    id: str = Field(description="Short container ID")
    name: str = Field(description="Container name")
    image: str = Field(description="Image name")
    status: str = Field(description="Container status (running, exited, etc.)")
    state: str = Field(description="Container state")
    ports: dict[str, str | None] = Field(
        default_factory=dict,
        description="Port mappings (container_port -> host_port)"
    )
    created: str = Field(description="Creation timestamp")


class ContainerStats(BaseModel):
    """Resource usage statistics for a container."""
    
    container_id: str
    container_name: str
    cpu_percent: float = Field(description="CPU usage percentage")
    memory_usage_mb: float = Field(description="Memory usage in MB")
    memory_limit_mb: float = Field(description="Memory limit in MB")
    memory_percent: float = Field(description="Memory usage percentage")
    network_rx_mb: float = Field(description="Network received in MB")
    network_tx_mb: float = Field(description="Network transmitted in MB")


class ContainerLogs(BaseModel):
    """Logs from a Docker container."""
    
    container_id: str
    container_name: str
    logs: str
    lines_returned: int


class ComposeStatus(BaseModel):
    """Status of a Docker Compose stack."""
    
    compose_file: str
    working_dir: str
    services: list[str]
    message: str


# =============================================================================
# Tool Registration
# =============================================================================

def register(mcp: FastMCP):
    """Register all Docker tools with the MCP server."""
    
    # =========================================================================
    # devenv_docker_list_containers - List all containers
    # [readOnly: true]
    # =========================================================================
    @mcp.tool()
    async def devenv_docker_list_containers(
        all: bool = False,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> list[ContainerInfo]:
        """
        List Docker containers with their status and details.
        
        Args:
            all: Include stopped containers (default: only running containers)
        
        Returns:
            List of container information including ID, name, status, and ports
        
        Example:
            - List running containers: devenv_docker_list_containers()
            - List all containers: devenv_docker_list_containers(all=True)
        """
        app_ctx = ctx.request_context.lifespan_context
        
        try:
            containers = app_ctx.docker.list_containers(all=all)
        except DockerUnavailableError as e:
            await ctx.error(str(e))
            return []
        
        result = []
        for container in containers:
            # Parse port mappings
            ports = {}
            port_bindings = container.attrs.get("NetworkSettings", {}).get("Ports", {})
            for container_port, bindings in (port_bindings or {}).items():
                if bindings:
                    host_port = bindings[0].get("HostPort")
                    ports[container_port] = host_port
                else:
                    ports[container_port] = None
            
            result.append(ContainerInfo(
                id=container.short_id,
                name=container.name,
                image=container.image.tags[0] if container.image.tags else container.image.short_id,
                status=container.status,
                state=container.attrs.get("State", {}).get("Status", "unknown"),
                ports=ports,
                created=container.attrs.get("Created", "unknown"),
            ))
        
        await ctx.info(f"Found {len(result)} container(s)")
        return result
    
    # =========================================================================
    # devenv_docker_start_container - Start a stopped container
    # [destructive: false]
    # =========================================================================
    @mcp.tool()
    async def devenv_docker_start_container(
        container_id: str,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> str:
        """
        Start a stopped Docker container.
        
        Args:
            container_id: Container ID or name
        
        Returns:
            Success message or error description
        """
        app_ctx = ctx.request_context.lifespan_context
        
        try:
            docker_client = app_ctx.docker.require_docker()
        except DockerUnavailableError as e:
            return f"Error: {e}"
        
        try:
            container = docker_client.containers.get(container_id)
            
            if container.status == "running":
                return f"Container '{container.name}' is already running"
            
            container.start()
            await ctx.info(f"Started container: {container.name}")
            return f"Successfully started container '{container.name}'"
            
        except Exception as e:
            error_msg = f"Failed to start container '{container_id}': {e}"
            await ctx.error(error_msg)
            return f"Error: {error_msg}"
    
    # =========================================================================
    # devenv_docker_stop_container - Stop a running container
    # [destructive: false]
    # =========================================================================
    @mcp.tool()
    async def devenv_docker_stop_container(
        container_id: str,
        timeout: int = 10,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> str:
        """
        Stop a running Docker container.
        
        Args:
            container_id: Container ID or name
            timeout: Seconds to wait before killing (default: 10)
        
        Returns:
            Success message or error description
        """
        app_ctx = ctx.request_context.lifespan_context
        
        try:
            docker_client = app_ctx.docker.require_docker()
        except DockerUnavailableError as e:
            return f"Error: {e}"
        
        try:
            container = docker_client.containers.get(container_id)
            
            if container.status != "running":
                return f"Container '{container.name}' is not running (status: {container.status})"
            
            await ctx.info(f"Stopping container: {container.name} (timeout: {timeout}s)")
            container.stop(timeout=timeout)
            return f"Successfully stopped container '{container.name}'"
            
        except Exception as e:
            error_msg = f"Failed to stop container '{container_id}': {e}"
            await ctx.error(error_msg)
            return f"Error: {error_msg}"
    
    # =========================================================================
    # devenv_docker_remove_container - Remove a container
    # [destructive: true] - Requires confirmation
    # =========================================================================
    @mcp.tool()
    async def devenv_docker_remove_container(
        container_id: str,
        force: bool = False,
        remove_volumes: bool = False,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> str:
        """
        Remove a Docker container. This action is IRREVERSIBLE.
        
        Args:
            container_id: Container ID or name
            force: Force remove even if running
            remove_volumes: Also remove associated volumes (DATA LOSS!)
        
        Returns:
            Success message or error description
        
        ⚠️ WARNING: This is a destructive operation that cannot be undone.
        """
        app_ctx = ctx.request_context.lifespan_context
        
        try:
            docker_client = app_ctx.docker.require_docker()
        except DockerUnavailableError as e:
            return f"Error: {e}"
        
        try:
            container = docker_client.containers.get(container_id)
            container_name = container.name
            
            # Request confirmation for destructive operation
            from pydantic import BaseModel as ConfirmModel
            
            class ConfirmRemove(ConfirmModel):
                confirm: bool = Field(
                    description="Set to true to confirm removal"
                )
            
            warning_msg = f"Are you sure you want to remove container '{container_name}'?"
            if remove_volumes:
                warning_msg += " This will also DELETE ALL ASSOCIATED VOLUMES AND DATA!"
            
            result = await ctx.elicit(
                message=warning_msg,
                schema=ConfirmRemove,
            )
            
            if result.action != "accept" or not result.data or not result.data.confirm:
                return "Container removal cancelled"
            
            # Proceed with removal
            container.remove(force=force, v=remove_volumes)
            await ctx.info(f"Removed container: {container_name}")
            return f"Successfully removed container '{container_name}'"
            
        except Exception as e:
            error_msg = f"Failed to remove container '{container_id}': {e}"
            await ctx.error(error_msg)
            return f"Error: {error_msg}"
    
    # =========================================================================
    # devenv_docker_logs - Get container logs
    # [readOnly: true]
    # =========================================================================
    @mcp.tool()
    async def devenv_docker_logs(
        container_id: str,
        tail: int = 100,
        since: str = None,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> ContainerLogs:
        """
        Get logs from a Docker container.
        
        Args:
            container_id: Container ID or name
            tail: Number of lines to return from the end (default: 100)
            since: Only return logs since this time (e.g., "1h", "2023-01-01")
        
        Returns:
            Container logs with metadata
        """
        app_ctx = ctx.request_context.lifespan_context
        
        try:
            docker_client = app_ctx.docker.require_docker()
        except DockerUnavailableError as e:
            return ContainerLogs(
                container_id=container_id,
                container_name="unknown",
                logs=f"Error: {e}",
                lines_returned=0,
            )
        
        try:
            container = docker_client.containers.get(container_id)
            
            # Get logs
            logs = container.logs(
                tail=tail,
                since=since,
                timestamps=True,
            ).decode("utf-8", errors="replace")
            
            lines = logs.strip().split("\n") if logs.strip() else []
            
            return ContainerLogs(
                container_id=container.short_id,
                container_name=container.name,
                logs=logs,
                lines_returned=len(lines),
            )
            
        except Exception as e:
            return ContainerLogs(
                container_id=container_id,
                container_name="unknown",
                logs=f"Error getting logs: {e}",
                lines_returned=0,
            )
    
    # =========================================================================
    # devenv_docker_stats - Get container resource usage
    # [readOnly: true]
    # =========================================================================
    @mcp.tool()
    async def devenv_docker_stats(
        container_id: str = None,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> list[ContainerStats]:
        """
        Get resource usage statistics for containers.
        
        Args:
            container_id: Specific container ID/name, or None for all running
        
        Returns:
            Resource usage including CPU, memory, and network I/O
        """
        app_ctx = ctx.request_context.lifespan_context
        
        try:
            docker_client = app_ctx.docker.require_docker()
        except DockerUnavailableError as e:
            await ctx.error(str(e))
            return []
        
        try:
            if container_id:
                containers = [docker_client.containers.get(container_id)]
            else:
                containers = docker_client.containers.list()
            
            results = []
            for container in containers:
                try:
                    stats = container.stats(stream=False)
                    
                    # Calculate CPU percentage
                    cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - \
                                stats["precpu_stats"]["cpu_usage"]["total_usage"]
                    system_delta = stats["cpu_stats"]["system_cpu_usage"] - \
                                   stats["precpu_stats"]["system_cpu_usage"]
                    cpu_count = stats["cpu_stats"].get("online_cpus", 1)
                    
                    if system_delta > 0:
                        cpu_percent = (cpu_delta / system_delta) * cpu_count * 100
                    else:
                        cpu_percent = 0.0
                    
                    # Memory stats
                    memory_usage = stats["memory_stats"].get("usage", 0)
                    memory_limit = stats["memory_stats"].get("limit", 1)
                    
                    # Network stats
                    networks = stats.get("networks", {})
                    rx_bytes = sum(n.get("rx_bytes", 0) for n in networks.values())
                    tx_bytes = sum(n.get("tx_bytes", 0) for n in networks.values())
                    
                    results.append(ContainerStats(
                        container_id=container.short_id,
                        container_name=container.name,
                        cpu_percent=round(cpu_percent, 2),
                        memory_usage_mb=round(memory_usage / 1024 / 1024, 2),
                        memory_limit_mb=round(memory_limit / 1024 / 1024, 2),
                        memory_percent=round((memory_usage / memory_limit) * 100, 2),
                        network_rx_mb=round(rx_bytes / 1024 / 1024, 2),
                        network_tx_mb=round(tx_bytes / 1024 / 1024, 2),
                    ))
                except Exception as e:
                    logger.warning(f"Failed to get stats for {container.name}: {e}")
            
            return results
            
        except Exception as e:
            await ctx.error(f"Failed to get container stats: {e}")
            return []
    
    # =========================================================================
    # devenv_docker_compose_up - Start a compose stack
    # [destructive: false]
    # =========================================================================
    @mcp.tool()
    async def devenv_docker_compose_up(
        working_dir: str = ".",
        compose_file: str = None,
        services: list[str] = None,
        build: bool = False,
        detach: bool = True,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> ComposeStatus:
        """
        Start services defined in a Docker Compose file.
        
        Args:
            working_dir: Directory containing the compose file (default: current)
            compose_file: Compose file name (auto-detects if not specified)
            services: Specific services to start (default: all)
            build: Build images before starting
            detach: Run in background (default: True)
        
        Returns:
            Status of the compose operation
        
        Example:
            - Start all services: devenv_docker_compose_up(working_dir="./backend")
            - Start specific service: devenv_docker_compose_up(services=["api", "db"])
        """
        app_ctx = ctx.request_context.lifespan_context
        work_path = Path(working_dir).expanduser().resolve()
        
        if not work_path.exists():
            return ComposeStatus(
                compose_file=compose_file or "unknown",
                working_dir=str(work_path),
                services=[],
                message=f"Error: Directory not found: {work_path}",
            )
        
        # Auto-detect compose file if not specified
        if compose_file is None:
            for candidate in app_ctx.config.default_compose_files:
                if (work_path / candidate).exists():
                    compose_file = candidate
                    await ctx.info(f"Auto-detected compose file: {candidate}")
                    break
            
            if compose_file is None:
                return ComposeStatus(
                    compose_file="not found",
                    working_dir=str(work_path),
                    services=[],
                    message=f"Error: No compose file found in {work_path}",
                )
        
        # Build command args
        args = ["up"]
        if detach:
            args.append("-d")
        if build:
            args.append("--build")
        if services:
            args.extend(services)
        
        await ctx.info(f"Starting compose stack in {work_path}")
        
        result = await run_docker_compose(
            args=args,
            compose_file=compose_file,
            working_dir=work_path,
        )
        
        if result.success:
            return ComposeStatus(
                compose_file=compose_file,
                working_dir=str(work_path),
                services=services or ["all"],
                message=f"Successfully started services\n{result.stdout}",
            )
        else:
            return ComposeStatus(
                compose_file=compose_file,
                working_dir=str(work_path),
                services=services or [],
                message=f"Error: {result.stderr or result.stdout}",
            )
    
    # =========================================================================
    # devenv_docker_compose_down - Stop a compose stack
    # [destructive: false]
    # =========================================================================
    @mcp.tool()
    async def devenv_docker_compose_down(
        working_dir: str = ".",
        compose_file: str = None,
        volumes: bool = False,
        remove_orphans: bool = True,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> ComposeStatus:
        """
        Stop and remove Docker Compose services.
        
        Args:
            working_dir: Directory containing the compose file
            compose_file: Compose file name (auto-detects if not specified)
            volumes: Also remove volumes (WARNING: data loss!)
            remove_orphans: Remove containers not defined in compose file
        
        Returns:
            Status of the compose operation
        """
        app_ctx = ctx.request_context.lifespan_context
        work_path = Path(working_dir).expanduser().resolve()
        
        if not work_path.exists():
            return ComposeStatus(
                compose_file=compose_file or "unknown",
                working_dir=str(work_path),
                services=[],
                message=f"Error: Directory not found: {work_path}",
            )
        
        # Auto-detect compose file
        if compose_file is None:
            for candidate in app_ctx.config.default_compose_files:
                if (work_path / candidate).exists():
                    compose_file = candidate
                    break
        
        # Build command args
        args = ["down"]
        if volumes:
            args.append("-v")
        if remove_orphans:
            args.append("--remove-orphans")
        
        # If removing volumes, request confirmation
        if volumes:
            from pydantic import BaseModel as ConfirmModel
            
            class ConfirmVolumeRemoval(ConfirmModel):
                confirm: bool = Field(
                    description="Set to true to confirm volume removal"
                )
            
            result = await ctx.elicit(
                message="Are you sure you want to remove volumes? This will DELETE ALL DATA!",
                schema=ConfirmVolumeRemoval,
            )
            
            if result.action != "accept" or not result.data or not result.data.confirm:
                return ComposeStatus(
                    compose_file=compose_file or "unknown",
                    working_dir=str(work_path),
                    services=[],
                    message="Operation cancelled - volumes not removed",
                )
        
        await ctx.info(f"Stopping compose stack in {work_path}")
        
        result = await run_docker_compose(
            args=args,
            compose_file=compose_file,
            working_dir=work_path,
        )
        
        return ComposeStatus(
            compose_file=compose_file or "unknown",
            working_dir=str(work_path),
            services=[],
            message=result.stdout if result.success else f"Error: {result.stderr}",
        )
    
    logger.info("Docker tools registered")
