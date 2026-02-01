"""
Environment variable and configuration management tools for DevEnv MCP.

These tools provide env var management and config file operations.
All tools are prefixed with `devenv_env_` or `devenv_config_` for namespacing.

TODO: Implement the following tools:
- devenv_env_list [readOnly: true]
- devenv_env_get [readOnly: true]
- devenv_env_set [destructive: false]
- devenv_config_read [readOnly: true]
- devenv_config_write [destructive: true]
"""

from mcp.server.fastmcp import FastMCP

from devenv_mcp.utils import get_logger

logger = get_logger("tools.environment")


def register(mcp: FastMCP):
    """Register all environment/config tools with the MCP server."""
    
    # TODO: Implement environment tools here following the pattern in docker.py
    # See SKILL.md for detailed specifications
    
    logger.info("Environment tools registered (not yet implemented)")
