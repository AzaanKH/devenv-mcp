"""
DevEnv MCP Server - Local Development Environment Manager

This MCP server enables AI agents to manage local development environments:
- Docker containers and compose stacks
- Python virtual environments
- Local databases (PostgreSQL, Redis)
- Development services and processes
- Environment variables and configuration
- System health monitoring

All tools are prefixed with `devenv_` for namespacing.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP

from devenv_mcp.utils.docker_client import DockerClientWrapper
from devenv_mcp.utils.logging_config import setup_logging

# Set up logging (writes to stderr for STDIO transport compatibility)
logger = setup_logging()


@dataclass
class AppConfig:
    """Application configuration loaded at startup."""
    
    default_venv_path: str = "~/.venvs"
    default_compose_files: list[str] = field(
        default_factory=lambda: [
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ]
    )
    sensitive_env_patterns: list[str] = field(
        default_factory=lambda: [
            "KEY", "SECRET", "TOKEN", "PASSWORD", 
            "CREDENTIAL", "AUTH", "PRIVATE"
        ]
    )


@dataclass
class AppContext:
    """
    Shared application context available to all tools via lifespan.
    
    This holds resources that are:
    - Expensive to create (like Docker client connections)
    - Need to be shared across all tool calls
    - Require proper cleanup when server stops
    
    Access in tools via: ctx.request_context.lifespan_context
    """
    
    docker: DockerClientWrapper
    config: AppConfig


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """
    Manage application lifecycle - startup and shutdown.
    
    This runs:
    - BEFORE the server starts accepting requests (setup)
    - AFTER the server stops accepting requests (cleanup)
    """
    logger.info("DevEnv MCP Server starting up...")
    
    # Initialize Docker client (gracefully handles Docker not being available)
    docker_wrapper = DockerClientWrapper()
    await docker_wrapper.connect()
    
    # Load configuration
    config = AppConfig()
    
    logger.info(f"Docker available: {docker_wrapper.is_available}")
    logger.info("Server ready to accept requests")
    
    try:
        yield AppContext(docker=docker_wrapper, config=config)
    finally:
        # Cleanup on shutdown
        logger.info("DevEnv MCP Server shutting down...")
        await docker_wrapper.close()
        logger.info("Cleanup complete")


# Create the MCP server instance
mcp = FastMCP(
    name="DevEnv Manager",
    instructions="""
    Local Development Environment Manager - helps you manage:
    
    🐳 Docker: Containers, compose stacks, images, and logs
    🐍 Python: Virtual environments and packages  
    🗄️ Databases: PostgreSQL and Redis (via Docker)
    ⚙️ Processes: Dev servers, ports, and services
    🔐 Environment: Variables and configuration files
    📊 Health: System resources and cleanup
    
    All tools are prefixed with 'devenv_' for easy discovery.
    Destructive operations will ask for confirmation.
    """,
    lifespan=app_lifespan,
)


# =============================================================================
# Register all tool modules
# =============================================================================
# Each module's register() function adds its tools to the mcp instance

from devenv_mcp.tools import docker as docker_tools
from devenv_mcp.tools import environment as env_tools
from devenv_mcp.tools import health as health_tools
from devenv_mcp.tools import process as process_tools
from devenv_mcp.tools import venv as venv_tools

docker_tools.register(mcp)
venv_tools.register(mcp)
process_tools.register(mcp)
env_tools.register(mcp)
health_tools.register(mcp)

# Resources
from devenv_mcp.resources import providers as resource_providers

resource_providers.register(mcp)


# =============================================================================
# Entry point
# =============================================================================

def main():
    """Run the DevEnv MCP server."""
    logger.info("Starting DevEnv MCP Server with STDIO transport")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
