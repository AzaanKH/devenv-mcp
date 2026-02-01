# DevEnv MCP Server

A Model Context Protocol (MCP) server for managing local development environments. Enables AI assistants like Claude to help manage Docker containers, Python virtual environments, processes, and system resources.

## Features

- **Docker Management** - Containers, compose stacks, logs, and stats
- **Python Environments** - Virtual environment creation, package management, and activation
- **Process Control** - Monitor dev processes and manage ports
- **System Health** - Resource monitoring, health checks, and cleanup tools

## Prerequisites

- Python 3.10+ (tested with 3.13.1)
- [uv](https://docs.astral.sh/uv/) - Fast Python package manager
- Docker Desktop (optional, but required for Docker tools)

## Installation

```bash
# Clone or navigate to the project
cd devenv-mcp

# Install dependencies with uv
uv sync

# Install dev dependencies (for testing)
uv sync --dev
```

## Usage

### Running the Server Directly

```bash
# Run with uv (recommended)
uv run devenv-mcp

# Or run the module directly
uv run python -m devenv_mcp.server
```

### Configuring with Claude Desktop

Add to your Claude Desktop configuration file:

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "devenv": {
      "command": "uv",
      "args": ["--directory", "C:\\Users\\Azaan\\Desktop\\mcp_servers\\devenv-mcp", "run", "devenv-mcp"]
    }
  }
}
```

### Configuring with Claude Code

Claude Code automatically discovers MCP servers. Add to your project's `.mcp.json`:

```json
{
  "servers": {
    "devenv": {
      "command": "uv",
      "args": ["--directory", "/path/to/devenv-mcp", "run", "devenv-mcp"]
    }
  }
}
```

## Available Tools

### Docker Tools

| Tool | Description | Destructive |
|------|-------------|-------------|
| `devenv_docker_list_containers` | List Docker containers | No (read-only) |
| `devenv_docker_start_container` | Start a stopped container | No |
| `devenv_docker_stop_container` | Stop a running container | No |
| `devenv_docker_remove_container` | Remove a container | **Yes** (confirmation required) |
| `devenv_docker_logs` | Get container logs | No (read-only) |
| `devenv_docker_stats` | Get container resource usage | No (read-only) |
| `devenv_docker_compose_up` | Start a compose stack | No |
| `devenv_docker_compose_down` | Stop a compose stack | No |

### Virtual Environment Tools

| Tool | Description | Destructive |
|------|-------------|-------------|
| `devenv_venv_list` | List virtual environments | No (read-only) |
| `devenv_venv_create` | Create a new venv | No |
| `devenv_venv_delete` | Delete a venv | **Yes** (confirmation required) |
| `devenv_venv_install` | Install packages into a venv | No |
| `devenv_venv_list_packages` | List installed packages | No (read-only) |
| `devenv_venv_activate_info` | Get activation command for shell | No (read-only) |

### Process Tools

| Tool | Description | Destructive |
|------|-------------|-------------|
| `devenv_process_list` | List dev processes (python, node, docker, etc.) | No (read-only) |
| `devenv_port_list` | List ports in use | No (read-only) |
| `devenv_port_kill` | Kill process on a port | **Yes** (confirmation required) |

### Health Tools

| Tool | Description | Destructive |
|------|-------------|-------------|
| `devenv_health_check` | Run health checks (Docker, disk, memory) | No (read-only) |
| `devenv_resource_usage` | Get CPU, memory, disk usage | No (read-only) |
| `devenv_cleanup` | Clean up unused Docker resources | **Yes** (confirmation required) |

## Resources

The server also provides MCP resources for reading data:

- `devenv://health` - System health status
- `devenv://containers` - Docker container list

## Development

### Running Tests

```bash
# Run unit tests (no Docker required)
uv run pytest tests/ -v

# Run integration tests (requires Docker)
uv run pytest tests/ -v --integration

# Run with coverage
uv run pytest tests/ -v --cov=src/devenv_mcp
```

### Code Quality

```bash
# Lint with ruff
uv run ruff check src/

# Format with ruff
uv run ruff format src/
```

### Project Structure

```
devenv-mcp/
├── pyproject.toml          # Project config & dependencies
├── README.md               # This file
├── CLAUDE.md               # Claude Code context file
├── src/devenv_mcp/
│   ├── __init__.py
│   ├── server.py           # Main FastMCP server & lifespan
│   ├── tools/
│   │   ├── docker.py       # Docker management tools
│   │   ├── venv.py         # Virtual environment tools
│   │   ├── process.py      # Process/port tools
│   │   └── health.py       # System health tools
│   ├── resources/
│   │   └── providers.py    # MCP resource providers
│   └── utils/
│       ├── logging_config.py  # STDIO-safe logging
│       ├── platform.py        # Cross-platform utilities
│       ├── docker_client.py   # Docker SDK wrapper
│       └── commands.py        # Shell command runner
└── tests/
    ├── conftest.py         # Pytest fixtures
    ├── test_docker.py      # Docker tool tests
    ├── test_venv.py        # Virtual environment tests
    ├── test_process.py     # Process/port tests
    └── test_health.py      # Health tool tests
```

## Error Handling

- **Docker unavailable**: Tools gracefully return error messages instead of crashing
- **Destructive operations**: Require explicit confirmation via MCP elicitation
- **Permission errors**: Handled gracefully with informative error messages

## Platform Support

- ✅ Windows (tested)
- ✅ macOS (supported)
- ✅ Linux (supported)

Cross-platform differences (paths, shells, executables) are handled by `utils/platform.py`.

## License

MIT
