"""
Process and port management tools for DevEnv MCP.

These tools provide process monitoring and port management for development workflows.
All tools are prefixed with `devenv_process_` or `devenv_port_` for namespacing.

Implemented tools:
- devenv_process_list [readOnly: true]
- devenv_port_list [readOnly: true]
- devenv_port_kill [destructive: true]
"""

from typing import TYPE_CHECKING

import psutil
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pydantic import BaseModel, Field

from devenv_mcp.utils import get_logger

if TYPE_CHECKING:
    from devenv_mcp.server import AppContext

logger = get_logger("tools.process")


# =============================================================================
# Data Models
# =============================================================================


class ProcessInfo(BaseModel):
    """Information about a running process."""

    pid: int = Field(description="Process ID")
    name: str = Field(description="Process name")
    cmdline: str = Field(description="Command line (truncated)")
    cpu_percent: float = Field(description="CPU usage percentage")
    memory_mb: float = Field(description="Memory usage in MB")
    status: str = Field(description="Process status (running, sleeping, etc.)")
    username: str = Field(description="User running the process")


class PortInfo(BaseModel):
    """Information about a port in use."""

    port: int = Field(description="Port number")
    protocol: str = Field(description="Protocol (tcp/udp)")
    pid: int | None = Field(description="Process ID using the port")
    process_name: str = Field(description="Name of the process using the port")
    status: str = Field(description="Connection status (LISTEN, ESTABLISHED, etc.)")
    local_address: str = Field(description="Local address (ip:port)")


# =============================================================================
# Constants
# =============================================================================

# Process names commonly used in development
DEV_PROCESS_NAMES = {
    "python", "python3", "python.exe",
    "node", "node.exe",
    "npm", "npm.exe", "npx", "npx.exe",
    "docker", "docker.exe", "dockerd",
    "java", "java.exe",
    "ruby", "ruby.exe",
    "go", "go.exe",
    "cargo", "rustc",
    "php", "php.exe",
    "postgres", "postgresql", "psql",
    "mysql", "mysqld",
    "redis-server", "redis-cli",
    "nginx", "apache", "httpd",
    "uvicorn", "gunicorn", "flask", "django",
    "next", "vite", "webpack",
    "code", "code.exe",  # VS Code
}

# Common development ports
COMMON_DEV_PORTS = {
    3000,  # React, Next.js
    3001,  # React alt
    4000,  # Various
    5000,  # Flask
    5173,  # Vite
    5432,  # PostgreSQL
    6379,  # Redis
    8000,  # Django, FastAPI, uvicorn
    8080,  # Various, Tomcat
    8888,  # Jupyter
    9000,  # PHP-FPM, various
    27017,  # MongoDB
}


# =============================================================================
# Helper Functions
# =============================================================================


def _is_dev_process(proc_name: str) -> bool:
    """Check if a process name is a common development tool."""
    name_lower = proc_name.lower()
    # Check exact match
    if name_lower in DEV_PROCESS_NAMES:
        return True
    # Check if name contains common dev tool names
    dev_keywords = ["python", "node", "npm", "docker", "java", "ruby", "go", "rust", "php"]
    return any(keyword in name_lower for keyword in dev_keywords)


def _get_process_info(proc: psutil.Process) -> ProcessInfo | None:
    """Extract process info safely, returning None if process is inaccessible."""
    try:
        with proc.oneshot():
            name = proc.name()
            cmdline = proc.cmdline()
            cmdline_str = " ".join(cmdline)[:200] if cmdline else name  # Truncate

            return ProcessInfo(
                pid=proc.pid,
                name=name,
                cmdline=cmdline_str,
                cpu_percent=round(proc.cpu_percent(interval=0.1), 1),
                memory_mb=round(proc.memory_info().rss / 1024 / 1024, 1),
                status=proc.status(),
                username=proc.username() if proc.username() else "unknown",
            )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return None


def _find_process_by_port(port: int) -> tuple[int | None, str]:
    """Find the process using a specific port. Returns (pid, process_name)."""
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port:
                if conn.pid:
                    try:
                        proc = psutil.Process(conn.pid)
                        return conn.pid, proc.name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        return conn.pid, "unknown"
                return None, "unknown"
    except psutil.AccessDenied:
        pass
    return None, ""


# =============================================================================
# Tool Registration
# =============================================================================


def register(mcp: FastMCP):
    """Register all process/port tools with the MCP server."""

    # =========================================================================
    # devenv_process_list - List development-related processes
    # [readOnly: true]
    # =========================================================================
    @mcp.tool()
    async def devenv_process_list(
        filter_dev_only: bool = True,
        name_filter: str = None,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> list[ProcessInfo]:
        """
        List running processes, optionally filtered to development tools.

        By default, shows only common development processes (python, node, docker, etc.).
        Set filter_dev_only=False to see all processes.

        Args:
            filter_dev_only: Only show development-related processes (default: True)
            name_filter: Filter by process name (case-insensitive substring match)

        Returns:
            List of ProcessInfo with pid, name, cmdline, cpu%, memory, status

        Example:
            - Dev processes only: devenv_process_list()
            - All processes: devenv_process_list(filter_dev_only=False)
            - Filter by name: devenv_process_list(name_filter="python")
        """
        processes = []

        for proc in psutil.process_iter():
            try:
                proc_name = proc.name()

                # Apply dev filter
                if filter_dev_only and not _is_dev_process(proc_name):
                    continue

                # Apply name filter
                if name_filter and name_filter.lower() not in proc_name.lower():
                    continue

                proc_info = _get_process_info(proc)
                if proc_info:
                    processes.append(proc_info)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Sort by CPU usage descending
        processes.sort(key=lambda p: p.cpu_percent, reverse=True)

        await ctx.info(f"Found {len(processes)} process(es)")
        return processes

    # =========================================================================
    # devenv_port_list - List ports in use
    # [readOnly: true]
    # =========================================================================
    @mcp.tool()
    async def devenv_port_list(
        filter_dev_ports: bool = True,
        port_range: tuple[int, int] = None,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> list[PortInfo]:
        """
        List ports currently in use on the system.

        By default, shows common development ports (3000, 5000, 8000, 8080, etc.).
        Set filter_dev_ports=False to see all listening ports.

        Args:
            filter_dev_ports: Only show common dev ports (default: True)
            port_range: Filter to ports in range (min, max), e.g., (8000, 9000)

        Returns:
            List of PortInfo with port, protocol, pid, process_name, status

        Example:
            - Common dev ports: devenv_port_list()
            - All ports: devenv_port_list(filter_dev_ports=False)
            - Port range: devenv_port_list(port_range=(8000, 9000))
        """
        ports = []
        seen_ports = set()  # Avoid duplicates

        try:
            connections = psutil.net_connections(kind="inet")
        except psutil.AccessDenied:
            await ctx.error("Access denied - may need elevated permissions to list all ports")
            connections = []

        for conn in connections:
            # Only interested in listening ports (servers) and established connections
            if conn.status not in ("LISTEN", "ESTABLISHED", "TIME_WAIT"):
                continue

            if not conn.laddr:
                continue

            port = conn.laddr.port

            # Skip if we've already seen this port
            port_key = (port, conn.type.name if hasattr(conn.type, 'name') else str(conn.type))
            if port_key in seen_ports:
                continue
            seen_ports.add(port_key)

            # Apply dev ports filter
            if filter_dev_ports and port not in COMMON_DEV_PORTS:
                continue

            # Apply port range filter
            if port_range:
                min_port, max_port = port_range
                if not (min_port <= port <= max_port):
                    continue

            # Get process info
            process_name = "unknown"
            if conn.pid:
                try:
                    proc = psutil.Process(conn.pid)
                    process_name = proc.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Determine protocol
            protocol = "tcp" if "TCP" in str(conn.type) else "udp"

            ports.append(PortInfo(
                port=port,
                protocol=protocol,
                pid=conn.pid,
                process_name=process_name,
                status=conn.status,
                local_address=f"{conn.laddr.ip}:{conn.laddr.port}",
            ))

        # Sort by port number
        ports.sort(key=lambda p: p.port)

        await ctx.info(f"Found {len(ports)} port(s) in use")
        return ports

    # =========================================================================
    # devenv_port_kill - Kill process using a specific port
    # [destructive: true] - Requires confirmation
    # =========================================================================
    @mcp.tool()
    async def devenv_port_kill(
        port: int,
        force: bool = False,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> str:
        """
        Kill the process using a specific port. This action is IRREVERSIBLE.

        Useful for freeing up ports when a dev server didn't shut down cleanly.

        Args:
            port: Port number to free up
            force: Use SIGKILL instead of SIGTERM (default: False)

        Returns:
            Success or error message

        Example:
            - Kill process on port 3000: devenv_port_kill(port=3000)
            - Force kill: devenv_port_kill(port=8080, force=True)

        ⚠️ WARNING: This will terminate the process immediately.
        """
        # Find the process using this port
        pid, process_name = _find_process_by_port(port)

        if pid is None:
            return f"No process found using port {port}"

        # Get more process info for confirmation
        try:
            proc = psutil.Process(pid)
            cmdline = " ".join(proc.cmdline())[:100] if proc.cmdline() else process_name
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            cmdline = process_name

        # Request confirmation
        from pydantic import BaseModel as ConfirmModel

        class ConfirmKill(ConfirmModel):
            confirm: bool = Field(description="Set to true to confirm killing the process")

        confirm_msg = f"Kill process using port {port}?\n"
        confirm_msg += f"  PID: {pid}\n"
        confirm_msg += f"  Process: {process_name}\n"
        confirm_msg += f"  Command: {cmdline}\n"
        if force:
            confirm_msg += "\n⚠️ FORCE mode: Process will be killed immediately (SIGKILL)"

        result = await ctx.elicit(
            message=confirm_msg,
            schema=ConfirmKill,
        )

        if result.action != "accept" or not result.data or not result.data.confirm:
            return "Operation cancelled"

        # Kill the process
        try:
            proc = psutil.Process(pid)

            if force:
                proc.kill()  # SIGKILL
                await ctx.info(f"Force killed process {pid} ({process_name})")
            else:
                proc.terminate()  # SIGTERM
                await ctx.info(f"Terminated process {pid} ({process_name})")

            # Wait a moment for the process to terminate
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                if not force:
                    await ctx.warning(f"Process {pid} didn't terminate gracefully, may need force=True")
                    return f"Process {pid} sent SIGTERM but may still be running. Use force=True to force kill."

            return f"Successfully killed process {pid} ({process_name}) - port {port} is now free"

        except psutil.NoSuchProcess:
            return f"Process {pid} no longer exists - port {port} may already be free"
        except psutil.AccessDenied:
            await ctx.error(f"Access denied killing process {pid}")
            return f"Error: Access denied - may need elevated permissions to kill process {pid}"
        except Exception as e:
            await ctx.error(f"Failed to kill process: {e}")
            return f"Error: Failed to kill process - {e}"

    logger.info("Process tools registered")
