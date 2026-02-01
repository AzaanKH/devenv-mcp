"""
Pytest configuration and fixtures for DevEnv MCP tests.

Provides fixtures for:
- Mock Docker client (unit tests)
- Real Docker client (integration tests)
- MCP server context
"""

import asyncio
from dataclasses import dataclass
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Pytest Configuration
# =============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests (require Docker)"
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless --integration flag is passed."""
    if config.getoption("--integration", default=False):
        return
    
    skip_integration = pytest.mark.skip(reason="need --integration flag to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="run integration tests (requires Docker)",
    )


# =============================================================================
# Mock Fixtures (Unit Tests)
# =============================================================================

@pytest.fixture
def mock_container():
    """Create a mock Docker container."""
    container = MagicMock()
    container.short_id = "abc123"
    container.name = "test-container"
    container.status = "running"
    container.attrs = {
        "Created": "2024-01-01T00:00:00Z",
        "State": {"Status": "running"},
        "NetworkSettings": {
            "Ports": {
                "8080/tcp": [{"HostPort": "8080"}],
                "5432/tcp": None,
            }
        },
    }
    container.image = MagicMock()
    container.image.tags = ["postgres:15"]
    container.image.short_id = "img123"
    container.logs.return_value = b"2024-01-01 Test log line\n"
    return container


@pytest.fixture
def mock_docker_client(mock_container):
    """Create a mock Docker client."""
    client = MagicMock()
    
    # Containers
    client.containers.list.return_value = [mock_container]
    client.containers.get.return_value = mock_container
    
    # Images
    mock_image = MagicMock()
    mock_image.tags = ["postgres:15"]
    mock_image.short_id = "img123"
    client.images.list.return_value = [mock_image]
    
    # System
    client.ping.return_value = True
    client.version.return_value = {"Version": "24.0.0"}
    client.info.return_value = {"Containers": 1}
    
    return client


@pytest.fixture
def mock_docker_wrapper(mock_docker_client):
    """Create a mock DockerClientWrapper."""
    from devenv_mcp.utils.docker_client import DockerClientWrapper
    
    wrapper = DockerClientWrapper()
    wrapper._client = mock_docker_client
    wrapper._is_available = True
    wrapper._unavailable_reason = None
    
    return wrapper


@pytest.fixture
def mock_app_context(mock_docker_wrapper):
    """Create a mock AppContext for testing tools."""
    from devenv_mcp.server import AppConfig, AppContext
    
    return AppContext(
        docker=mock_docker_wrapper,
        config=AppConfig(),
    )


@pytest.fixture
def mock_mcp_context(mock_app_context):
    """Create a mock MCP Context with request_context."""
    context = MagicMock()
    context.request_context = MagicMock()
    context.request_context.lifespan_context = mock_app_context
    
    # Mock logging methods as async
    context.info = AsyncMock()
    context.error = AsyncMock()
    context.warning = AsyncMock()
    context.debug = AsyncMock()
    
    # Mock elicit for confirmation dialogs
    async def mock_elicit(message, schema):
        result = MagicMock()
        result.action = "accept"
        result.data = MagicMock()
        result.data.confirm = True
        return result
    
    context.elicit = mock_elicit
    
    return context


# =============================================================================
# Integration Test Fixtures (Real Docker)
# =============================================================================

@pytest.fixture(scope="session")
def docker_available() -> bool:
    """Check if Docker is available for integration tests."""
    try:
        import docker
        client = docker.from_env()
        client.ping()
        client.close()
        return True
    except Exception:
        return False


@pytest.fixture
def real_docker_client(docker_available):
    """Get a real Docker client for integration tests."""
    if not docker_available:
        pytest.skip("Docker not available")
    
    import docker
    client = docker.from_env()
    yield client
    client.close()


@pytest.fixture
async def integration_app_context(docker_available) -> AsyncGenerator:
    """Create a real AppContext for integration tests."""
    if not docker_available:
        pytest.skip("Docker not available")
    
    from devenv_mcp.server import AppConfig, AppContext
    from devenv_mcp.utils.docker_client import DockerClientWrapper
    
    docker_wrapper = DockerClientWrapper()
    await docker_wrapper.connect()
    
    ctx = AppContext(
        docker=docker_wrapper,
        config=AppConfig(),
    )
    
    yield ctx
    
    await docker_wrapper.close()


# =============================================================================
# Command Execution Fixtures
# =============================================================================

@pytest.fixture
def mock_run_command():
    """Mock the run_command function."""
    from devenv_mcp.utils.commands import CommandResult
    
    async def _mock_run(command, **kwargs):
        return CommandResult(
            returncode=0,
            stdout="Success",
            stderr="",
            command=str(command),
        )
    
    with patch("devenv_mcp.utils.commands.run_command", side_effect=_mock_run) as mock:
        yield mock


@pytest.fixture
def mock_run_docker_compose():
    """Mock the run_docker_compose function."""
    from devenv_mcp.utils.commands import CommandResult
    
    async def _mock_compose(args, **kwargs):
        return CommandResult(
            returncode=0,
            stdout="Creating network... done\nStarting service... done",
            stderr="",
            command=f"docker compose {' '.join(args)}",
        )
    
    with patch("devenv_mcp.tools.docker.run_docker_compose", side_effect=_mock_compose) as mock:
        yield mock
