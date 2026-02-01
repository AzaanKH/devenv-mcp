"""
Utilities for executing shell commands safely and cross-platform.

Provides async command execution with proper error handling,
timeout support, and output capture.
"""

import asyncio
import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from devenv_mcp.utils.logging_config import get_logger
from devenv_mcp.utils.platform import PlatformHelper

logger = get_logger("utils.commands")


@dataclass
class CommandResult:
    """Result of a command execution."""
    
    returncode: int
    stdout: str
    stderr: str
    command: str
    
    @property
    def success(self) -> bool:
        """Check if command succeeded (return code 0)."""
        return self.returncode == 0
    
    @property
    def output(self) -> str:
        """Get combined stdout and stderr."""
        parts = []
        if self.stdout:
            parts.append(self.stdout)
        if self.stderr:
            parts.append(self.stderr)
        return "\n".join(parts)


class CommandError(Exception):
    """Raised when a command fails."""
    
    def __init__(self, result: CommandResult):
        self.result = result
        message = f"Command failed with code {result.returncode}: {result.command}"
        if result.stderr:
            message += f"\nError: {result.stderr}"
        super().__init__(message)


async def run_command(
    command: list[str] | str,
    cwd: str | Path = None,
    env: Mapping[str, str] = None,
    timeout: float = 60.0,
    check: bool = False,
    shell: bool = False,
) -> CommandResult:
    """
    Execute a command asynchronously.
    
    Args:
        command: Command as list of args or string (if shell=True)
        cwd: Working directory for the command
        env: Environment variables (merged with current env)
        timeout: Timeout in seconds
        check: If True, raise CommandError on non-zero exit
        shell: If True, run through shell (use with caution!)
        
    Returns:
        CommandResult with output and return code
        
    Raises:
        CommandError: If check=True and command fails
        asyncio.TimeoutError: If command exceeds timeout
    """
    # Prepare command string for logging
    if isinstance(command, list):
        command_str = " ".join(shlex.quote(arg) for arg in command)
    else:
        command_str = command
    
    logger.debug(f"Running command: {command_str}")
    
    # Prepare working directory
    if cwd is not None:
        cwd = str(Path(cwd).expanduser().resolve())
    
    # Prepare environment
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    
    try:
        if shell:
            # Shell mode - command should be a string
            if isinstance(command, list):
                command = " ".join(shlex.quote(arg) for arg in command)
            
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=full_env,
            )
        else:
            # Non-shell mode - command should be a list
            if isinstance(command, str):
                command = shlex.split(command)
            
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=full_env,
            )
        
        # Wait for completion with timeout
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
        
        result = CommandResult(
            returncode=process.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace").strip(),
            stderr=stderr_bytes.decode("utf-8", errors="replace").strip(),
            command=command_str,
        )
        
        logger.debug(f"Command completed with code {result.returncode}")
        
        if check and not result.success:
            raise CommandError(result)
        
        return result
        
    except asyncio.TimeoutError:
        logger.error(f"Command timed out after {timeout}s: {command_str}")
        raise
    except FileNotFoundError as e:
        # Command not found
        logger.error(f"Command not found: {command_str}")
        return CommandResult(
            returncode=127,
            stdout="",
            stderr=f"Command not found: {e.filename}",
            command=command_str,
        )


async def run_docker_compose(
    args: list[str],
    compose_file: str = None,
    working_dir: str | Path = None,
    env: Mapping[str, str] = None,
    timeout: float = 120.0,
) -> CommandResult:
    """
    Run a docker compose command.
    
    Uses 'docker compose' (v2) syntax.
    
    Args:
        args: Arguments to pass to docker compose (e.g., ["up", "-d"])
        compose_file: Path to compose file (optional)
        working_dir: Working directory
        env: Additional environment variables
        timeout: Timeout in seconds
        
    Returns:
        CommandResult
    """
    command = ["docker", "compose"]
    
    if compose_file:
        command.extend(["-f", compose_file])
    
    command.extend(args)
    
    return await run_command(
        command,
        cwd=working_dir,
        env=env,
        timeout=timeout,
    )


def check_command_available(command: str) -> bool:
    """
    Check if a command is available in PATH.
    
    Args:
        command: Command name (e.g., 'docker', 'python')
        
    Returns:
        True if command is available
    """
    return PlatformHelper.is_executable_available(command)
