"""
Logging configuration for DevEnv MCP Server.

IMPORTANT: For STDIO transport, we MUST write logs to stderr, not stdout.
Writing to stdout corrupts the JSON-RPC messages and breaks the MCP protocol.
"""

import logging
import sys


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Configure logging to write to stderr for STDIO transport compatibility.
    
    Args:
        level: Logging level (default: INFO)
    
    Returns:
        Configured logger instance
    """
    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    
    # Create stderr handler (CRITICAL: not stdout!)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(formatter)
    handler.setLevel(level)
    
    # Configure root logger for our package
    logger = logging.getLogger("devenv_mcp")
    logger.setLevel(level)
    logger.addHandler(handler)
    
    # Prevent propagation to root logger (avoids duplicate logs)
    logger.propagate = False
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a child logger for a specific module.
    
    Args:
        name: Module name (e.g., "tools.docker")
    
    Returns:
        Logger instance
    
    Example:
        logger = get_logger("tools.docker")
        logger.info("Starting container...")
    """
    return logging.getLogger(f"devenv_mcp.{name}")
