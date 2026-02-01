# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DevEnv MCP is a Model Context Protocol server that enables AI assistants to manage local development environments. Built with FastMCP Python SDK, it exposes tools for Docker, virtual environments, databases, and system management.

## Commands

```bash
uv sync                                    # Install dependencies
uv run devenv-mcp                          # Run the server
uv run pytest tests/ -v                    # Run unit tests
uv run pytest tests/ -v --integration      # Run integration tests (requires Docker)
uv run pytest tests/test_docker.py::test_name -v  # Run single test
uv run ruff check src/                     # Lint
uv run ruff format src/                    # Format
```

## Architecture

### Core Flow

`server.py` creates a `FastMCP` instance with a lifespan context manager that initializes shared resources (`AppContext`). Tool modules register themselves via `register(mcp)` functions.

```
server.py (FastMCP + lifespan)
    ├── AppContext (shared state: DockerClientWrapper, AppConfig)
    ├── tools/*.py (register tools via @mcp.tool decorator)
    ├── resources/providers.py (MCP resources)
    └── utils/ (logging, commands, platform helpers)
```

### Accessing Shared Context in Tools

```python
@mcp.tool()
async def devenv_example_tool(ctx: Context[ServerSession, "AppContext"] = None) -> str:
    app_ctx = ctx.request_context.lifespan_context
    docker_client = app_ctx.docker.require_docker()  # Raises DockerUnavailableError if unavailable
    config = app_ctx.config
```

### Tool Naming

All tools: `devenv_{category}_{action}` (e.g., `devenv_docker_list_containers`, `devenv_venv_create`)

### Tool Categories by File

- `tools/docker.py` - Docker/containers (implemented)
- `tools/venv.py` - Virtual environments (fully implemented)
- `tools/process.py` - Processes/ports (fully implemented)
- `tools/health.py` - Health/monitoring (fully implemented)

## Key Patterns

### Destructive Operations

Use `ctx.elicit()` for confirmation on irreversible actions:

```python
class ConfirmAction(BaseModel):
    confirm: bool = Field(description="Set to true to confirm")

result = await ctx.elicit(message="Are you sure?", schema=ConfirmAction)
if result.action != "accept" or not result.data or not result.data.confirm:
    return "Operation cancelled"
```

### Shell Commands

Use `run_command` / `run_docker_compose` from `devenv_mcp.utils.commands` (never `subprocess` directly).

### Cross-Platform

Use `PlatformHelper` from `devenv_mcp.utils.platform` for paths and shell differences.

### Logging

**Never use `print()`** - breaks STDIO transport. Use:
- `get_logger("tools.mymodule")` for module-level logging
- `await ctx.info/error/warning()` inside tools (preferred)

## Tool Designs

### Venv Tools (Fully Implemented)

**Status**: ✅ All 6 tools implemented in `tools/venv.py` with 41 tests in `tests/test_venv.py`

| Tool | Purpose | Destructive |
|------|---------|-------------|
| `devenv_venv_list` | List venvs with Python version and package count | No |
| `devenv_venv_create` | Create new venv using `python -m venv` | No |
| `devenv_venv_delete` | Delete venv directory | Yes (confirmation) |
| `devenv_venv_install` | Install packages via pip | No |
| `devenv_venv_list_packages` | List installed packages in a venv | No |
| `devenv_venv_activate_info` | Get activation command for shell | No |

**Key Implementation Details**:
- Discovery: Checks `working_dir` for `./venv` and `./.venv`, then `~/.venvs/` if `include_global=True`
- Venv detection: Valid if `Scripts/python.exe` (Windows) or `bin/python` (Unix) exists
- Parallel execution: `asyncio.gather` runs `python --version` + `pip list --format=json` concurrently
- Error tolerance: Broken venvs return `is_valid=False`, `python_version="unknown"`, `packages_count=0`
- uv compatibility: `uv`-managed venvs may not have pip, so `packages_count=0` is valid
- Safety: `devenv_venv_delete` checks for venv markers before deletion to prevent accidental data loss

### Process Tools (Fully Implemented)

**Status**: ✅ All 3 tools implemented in `tools/process.py` with 18 tests in `tests/test_process.py`

| Tool | Purpose | Destructive |
|------|---------|-------------|
| `devenv_process_list` | List dev processes (python, node, docker, etc.) | No |
| `devenv_port_list` | List ports in use (common dev ports by default) | No |
| `devenv_port_kill` | Kill process using a specific port | Yes (confirmation) |

**Key Implementation Details**:
- Uses `psutil` for cross-platform process and network inspection
- `DEV_PROCESS_NAMES` constant defines recognized dev tools (python, node, docker, etc.)
- `COMMON_DEV_PORTS` constant defines common ports (3000, 5000, 8000, 8080, etc.)
- Process filtering by name substring and dev-only mode
- Port filtering by range or dev-ports-only mode
- `devenv_port_kill` supports both SIGTERM (default) and SIGKILL (force=True)

### Health Tools (Fully Implemented)

**Status**: ✅ All 3 tools implemented in `tools/health.py` with 21 tests in `tests/test_health.py`

| Tool | Purpose | Destructive |
|------|---------|-------------|
| `devenv_health_check` | Check Docker, disk space, memory with status thresholds | No |
| `devenv_resource_usage` | Get CPU, memory, disk stats via psutil | No |
| `devenv_cleanup` | Prune Docker containers, images, networks | Yes (confirmation) |

**Key Implementation Details**:
- Uses `psutil` for cross-platform system resource monitoring
- Thresholds: disk warning at 80%, critical at 95%; memory warning at 85%, critical at 95%
- Health check returns overall status (healthy/degraded/unhealthy) based on component statuses
- `devenv_cleanup` prunes containers, images, networks by default; volumes disabled to prevent data loss
- Windows compatibility: `load_average` returns None (only available on Unix)
- Skips special filesystems (tmpfs, squashfs, devtmpfs) when enumerating disk partitions

## Testing

- `mock_mcp_context` fixture provides mocked `AppContext` and Docker client
- `@pytest.mark.integration` for tests requiring real Docker (skipped without `--integration` flag)
- `mock_run_command` / `mock_run_docker_compose` fixtures for command mocking
