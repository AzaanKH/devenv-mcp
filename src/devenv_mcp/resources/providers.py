"""
MCP Resources for DevEnv.

Resources provide URI-based access to data that can be read by the AI.
Unlike tools, resources are for reading data, not performing actions.

URI Scheme:
- devenv://health - System health status
- devenv://containers - List of Docker containers
- devenv://containers/{id} - Specific container details

TODO: Add more resources:
- devenv://venvs - Virtual environments
- devenv://databases - Database services
- devenv://config/{name} - Configuration files
"""

from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP

from devenv_mcp.utils import DockerUnavailableError, get_logger

if TYPE_CHECKING:
    from devenv_mcp.server import AppContext

logger = get_logger("resources.providers")


def register(mcp: FastMCP):
    """Register all resources with the MCP server."""
    
    # =========================================================================
    # devenv://health - System health overview
    # =========================================================================
    @mcp.resource("devenv://health")
    async def get_health_resource() -> str:
        """
        Get system health status.
        
        Returns a summary of:
        - Docker availability
        - System resources (CPU, memory, disk)
        - Running services
        """
        import psutil
        
        lines = ["# DevEnv Health Status", ""]
        
        # System resources
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        
        lines.append("## System Resources")
        lines.append(f"- CPU Usage: {cpu_percent}%")
        lines.append(f"- Memory: {memory.percent}% used ({memory.used // 1024 // 1024} MB / {memory.total // 1024 // 1024} MB)")
        lines.append(f"- Disk: {disk.percent}% used ({disk.used // 1024 // 1024 // 1024} GB / {disk.total // 1024 // 1024 // 1024} GB)")
        lines.append("")
        
        # Docker status (we can't access lifespan context from resources easily,
        # so we check Docker availability directly)
        try:
            import docker
            client = docker.from_env()
            client.ping()
            version = client.version().get("Version", "unknown")
            containers = len(client.containers.list())
            lines.append("## Docker")
            lines.append(f"- Status: ✅ Available (version {version})")
            lines.append(f"- Running containers: {containers}")
            client.close()
        except Exception as e:
            lines.append("## Docker")
            lines.append(f"- Status: ❌ Unavailable ({e})")
        
        return "\n".join(lines)
    
    # =========================================================================
    # devenv://containers - List all containers
    # =========================================================================
    @mcp.resource("devenv://containers")
    async def get_containers_resource() -> str:
        """
        Get list of all Docker containers.
        
        Returns markdown-formatted list of containers with status.
        """
        try:
            import docker
            client = docker.from_env()
            containers = client.containers.list(all=True)
            
            if not containers:
                return "# Docker Containers\n\nNo containers found."
            
            lines = ["# Docker Containers", ""]
            lines.append("| Name | Status | Image | Ports |")
            lines.append("|------|--------|-------|-------|")
            
            for c in containers:
                # Get port mappings
                ports = c.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
                port_str = ", ".join(
                    f"{k}->{v[0]['HostPort']}" if v else k
                    for k, v in ports.items()
                ) or "none"
                
                image = c.image.tags[0] if c.image.tags else c.image.short_id
                status_emoji = "🟢" if c.status == "running" else "🔴"
                
                lines.append(f"| {c.name} | {status_emoji} {c.status} | {image} | {port_str} |")
            
            client.close()
            return "\n".join(lines)
            
        except Exception as e:
            return f"# Docker Containers\n\nError: {e}"
    
    logger.info("Resources registered")
