"""
Tests for virtual environment tools.

Tests both unit tests (mocked) and integration tests (real venvs).
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from devenv_mcp.tools.venv import (
    VenvInfo,
    _discover_venvs,
    _get_venv_info,
    _is_valid_venv,
)
from devenv_mcp.utils.commands import CommandResult

# =============================================================================
# Unit Tests - _is_valid_venv
# =============================================================================


class TestIsValidVenv:
    """Tests for _is_valid_venv helper function."""

    def test_valid_venv_windows(self, tmp_path):
        """Test detection of valid venv on Windows-style structure."""
        venv_path = tmp_path / "test_venv"
        scripts_dir = venv_path / "Scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "python.exe").touch()

        with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_python_path") as mock:
            mock.return_value = scripts_dir / "python.exe"
            assert _is_valid_venv(venv_path) is True

    def test_valid_venv_unix(self, tmp_path):
        """Test detection of valid venv on Unix-style structure."""
        venv_path = tmp_path / "test_venv"
        bin_dir = venv_path / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "python").touch()

        with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_python_path") as mock:
            mock.return_value = bin_dir / "python"
            assert _is_valid_venv(venv_path) is True

    def test_invalid_venv_no_python(self, tmp_path):
        """Test detection of invalid venv (no python executable)."""
        venv_path = tmp_path / "test_venv"
        venv_path.mkdir()

        with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_python_path") as mock:
            mock.return_value = venv_path / "bin" / "python"
            assert _is_valid_venv(venv_path) is False

    def test_invalid_venv_empty_dir(self, tmp_path):
        """Test detection of invalid venv (empty directory)."""
        venv_path = tmp_path / "empty_dir"
        venv_path.mkdir()

        with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_python_path") as mock:
            mock.return_value = venv_path / "Scripts" / "python.exe"
            assert _is_valid_venv(venv_path) is False


# =============================================================================
# Unit Tests - _discover_venvs
# =============================================================================


class TestDiscoverVenvs:
    """Tests for _discover_venvs helper function."""

    def test_discovers_local_venv(self, tmp_path):
        """Test discovering ./venv in working directory."""
        venv_path = tmp_path / "venv"
        venv_path.mkdir()

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_default_venv_location",
                return_value=tmp_path / "nonexistent",
            ):
                result = _discover_venvs(tmp_path, include_global=False, name_pattern=None)

        assert len(result) == 1
        assert result[0] == venv_path

    def test_discovers_local_dot_venv(self, tmp_path):
        """Test discovering ./.venv in working directory."""
        venv_path = tmp_path / ".venv"
        venv_path.mkdir()

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_default_venv_location",
                return_value=tmp_path / "nonexistent",
            ):
                result = _discover_venvs(tmp_path, include_global=False, name_pattern=None)

        assert len(result) == 1
        assert result[0] == venv_path

    def test_discovers_both_local_venvs(self, tmp_path):
        """Test discovering both ./venv and ./.venv."""
        (tmp_path / "venv").mkdir()
        (tmp_path / ".venv").mkdir()

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_default_venv_location",
                return_value=tmp_path / "nonexistent",
            ):
                result = _discover_venvs(tmp_path, include_global=False, name_pattern=None)

        assert len(result) == 2

    def test_discovers_global_venvs(self, tmp_path):
        """Test discovering venvs in ~/.venvs/."""
        global_dir = tmp_path / ".venvs"
        global_dir.mkdir()
        (global_dir / "project-a").mkdir()
        (global_dir / "project-b").mkdir()

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_default_venv_location",
                return_value=global_dir,
            ):
                result = _discover_venvs(tmp_path, include_global=True, name_pattern=None)

        assert len(result) == 2

    def test_excludes_global_when_disabled(self, tmp_path):
        """Test that include_global=False excludes ~/.venvs/."""
        global_dir = tmp_path / ".venvs"
        global_dir.mkdir()
        (global_dir / "project-a").mkdir()

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_default_venv_location",
                return_value=global_dir,
            ):
                result = _discover_venvs(tmp_path, include_global=False, name_pattern=None)

        assert len(result) == 0

    def test_filters_by_name_pattern(self, tmp_path):
        """Test filtering venvs by glob pattern."""
        global_dir = tmp_path / ".venvs"
        global_dir.mkdir()
        (global_dir / "project-a").mkdir()
        (global_dir / "project-b").mkdir()
        (global_dir / "other-venv").mkdir()

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_default_venv_location",
                return_value=global_dir,
            ):
                result = _discover_venvs(tmp_path, include_global=True, name_pattern="project-*")

        assert len(result) == 2
        names = [p.name for p in result]
        assert "project-a" in names
        assert "project-b" in names
        assert "other-venv" not in names

    def test_skips_invalid_venvs(self, tmp_path):
        """Test that invalid venvs are not included."""
        (tmp_path / "venv").mkdir()
        (tmp_path / ".venv").mkdir()

        def mock_is_valid(path):
            return path.name == "venv"  # Only venv is valid

        with patch("devenv_mcp.tools.venv._is_valid_venv", side_effect=mock_is_valid):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_default_venv_location",
                return_value=tmp_path / "nonexistent",
            ):
                result = _discover_venvs(tmp_path, include_global=False, name_pattern=None)

        assert len(result) == 1
        assert result[0].name == "venv"


# =============================================================================
# Unit Tests - _get_venv_info
# =============================================================================


class TestGetVenvInfo:
    """Tests for _get_venv_info helper function."""

    @pytest.mark.asyncio
    async def test_returns_info_for_valid_venv(self, tmp_path):
        """Test getting info for a valid venv."""
        venv_path = tmp_path / "test_venv"
        venv_path.mkdir()
        scripts = venv_path / "Scripts"
        scripts.mkdir()
        (scripts / "python.exe").touch()
        (scripts / "pip.exe").touch()

        version_result = CommandResult(
            returncode=0,
            stdout="Python 3.11.5",
            stderr="",
            command="python --version",
        )
        packages_result = CommandResult(
            returncode=0,
            stdout=json.dumps([{"name": "pip", "version": "23.0"}, {"name": "setuptools", "version": "65.0"}]),
            stderr="",
            command="pip list --format=json",
        )

        with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_python_path") as mock_python:
            with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_pip_path") as mock_pip:
                with patch("devenv_mcp.tools.venv.run_command") as mock_run:
                    mock_python.return_value = scripts / "python.exe"
                    mock_pip.return_value = scripts / "pip.exe"
                    mock_run.side_effect = [version_result, packages_result]

                    result = await _get_venv_info(venv_path)

        assert result.name == "test_venv"
        assert result.path == str(venv_path)
        assert result.python_version == "3.11.5"
        assert result.packages_count == 2
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_returns_invalid_for_missing_python(self, tmp_path):
        """Test handling of venv with missing python executable."""
        venv_path = tmp_path / "broken_venv"
        venv_path.mkdir()

        with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_python_path") as mock_python:
            with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_pip_path") as mock_pip:
                mock_python.return_value = venv_path / "Scripts" / "python.exe"  # Doesn't exist
                mock_pip.return_value = venv_path / "Scripts" / "pip.exe"

                result = await _get_venv_info(venv_path)

        assert result.name == "broken_venv"
        assert result.python_version == "unknown"
        assert result.packages_count == 0
        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_handles_failed_version_command(self, tmp_path):
        """Test handling of failed python --version command."""
        venv_path = tmp_path / "test_venv"
        venv_path.mkdir()
        scripts = venv_path / "Scripts"
        scripts.mkdir()
        (scripts / "python.exe").touch()
        (scripts / "pip.exe").touch()

        version_result = CommandResult(
            returncode=1,
            stdout="",
            stderr="Error",
            command="python --version",
        )
        packages_result = CommandResult(
            returncode=0,
            stdout=json.dumps([{"name": "pip", "version": "23.0"}]),
            stderr="",
            command="pip list --format=json",
        )

        with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_python_path") as mock_python:
            with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_pip_path") as mock_pip:
                with patch("devenv_mcp.tools.venv.run_command") as mock_run:
                    mock_python.return_value = scripts / "python.exe"
                    mock_pip.return_value = scripts / "pip.exe"
                    mock_run.side_effect = [version_result, packages_result]

                    result = await _get_venv_info(venv_path)

        assert result.python_version == "unknown"
        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_handles_invalid_json_from_pip(self, tmp_path):
        """Test handling of invalid JSON from pip list."""
        venv_path = tmp_path / "test_venv"
        venv_path.mkdir()
        scripts = venv_path / "Scripts"
        scripts.mkdir()
        (scripts / "python.exe").touch()
        (scripts / "pip.exe").touch()

        version_result = CommandResult(
            returncode=0,
            stdout="Python 3.11.5",
            stderr="",
            command="python --version",
        )
        packages_result = CommandResult(
            returncode=0,
            stdout="not valid json",
            stderr="",
            command="pip list --format=json",
        )

        with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_python_path") as mock_python:
            with patch("devenv_mcp.tools.venv.PlatformHelper.get_venv_pip_path") as mock_pip:
                with patch("devenv_mcp.tools.venv.run_command") as mock_run:
                    mock_python.return_value = scripts / "python.exe"
                    mock_pip.return_value = scripts / "pip.exe"
                    mock_run.side_effect = [version_result, packages_result]

                    result = await _get_venv_info(venv_path)

        assert result.python_version == "3.11.5"
        assert result.packages_count == 0  # Couldn't parse, defaults to 0
        assert result.is_valid is True  # Still valid if python works


# =============================================================================
# Unit Tests - devenv_venv_list tool
# =============================================================================


class TestDevenvVenvList:
    """Tests for the devenv_venv_list MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_venvs(self, mock_mcp_context, tmp_path):
        """Test returning empty list when no venvs are found."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.venv import register

        mcp = FastMCP("test")
        register(mcp)

        # Get the registered tool
        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_venv_list":
                tool_fn = tool.fn
                break

        assert tool_fn is not None

        with patch("devenv_mcp.tools.venv._discover_venvs", return_value=[]):
            result = await tool_fn(
                working_dir=str(tmp_path),
                include_global=False,
                name_pattern=None,
                ctx=mock_mcp_context,
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_venv_info_list(self, mock_mcp_context, tmp_path):
        """Test returning list of VenvInfo objects."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.venv import register

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_venv_list":
                tool_fn = tool.fn
                break

        venv_path = tmp_path / ".venv"
        mock_venv_info = VenvInfo(
            name=".venv",
            path=str(venv_path),
            python_version="3.11.5",
            packages_count=10,
            is_valid=True,
        )

        with patch("devenv_mcp.tools.venv._discover_venvs", return_value=[venv_path]):
            with patch("devenv_mcp.tools.venv._get_venv_info", return_value=mock_venv_info):
                result = await tool_fn(
                    working_dir=str(tmp_path),
                    include_global=False,
                    name_pattern=None,
                    ctx=mock_mcp_context,
                )

        assert len(result) == 1
        assert result[0].name == ".venv"
        assert result[0].python_version == "3.11.5"
        assert result[0].packages_count == 10
        assert result[0].is_valid is True

    @pytest.mark.asyncio
    async def test_handles_nonexistent_working_dir(self, mock_mcp_context, tmp_path):
        """Test handling of nonexistent working directory."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.venv import register

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_venv_list":
                tool_fn = tool.fn
                break

        with patch("devenv_mcp.tools.venv._discover_venvs", return_value=[]):
            result = await tool_fn(
                working_dir=str(tmp_path / "nonexistent"),
                include_global=False,
                name_pattern=None,
                ctx=mock_mcp_context,
            )

        # Should fall back to cwd and return empty list
        assert result == []
        # Should have logged a warning
        mock_mcp_context.warning.assert_called()


# =============================================================================
# Unit Tests - devenv_venv_create tool
# =============================================================================


class TestDevenvVenvCreate:
    """Tests for the devenv_venv_create MCP tool."""

    def _get_tool_fn(self, tool_name: str):
        """Helper to get a registered tool function."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.venv import register

        mcp = FastMCP("test")
        register(mcp)

        for tool in mcp._tool_manager._tools.values():
            if tool.name == tool_name:
                return tool.fn
        return None

    @pytest.mark.asyncio
    async def test_creates_venv_in_default_location(self, mock_mcp_context, tmp_path):
        """Test creating venv in default ~/.venvs/ location."""
        tool_fn = self._get_tool_fn("devenv_venv_create")
        assert tool_fn is not None

        # Mock the default venv location to use tmp_path
        global_venvs = tmp_path / ".venvs"

        # Mock python check and venv creation
        python_check_result = CommandResult(
            returncode=0,
            stdout="Python 3.11.5",
            stderr="",
            command="python --version",
        )
        venv_create_result = CommandResult(
            returncode=0,
            stdout="",
            stderr="",
            command="python -m venv",
        )

        mock_venv_info = VenvInfo(
            name="test-project",
            path=str(global_venvs / "test-project"),
            python_version="3.11.5",
            packages_count=2,
            is_valid=True,
        )

        with patch(
            "devenv_mcp.tools.venv.PlatformHelper.get_default_venv_location",
            return_value=global_venvs,
        ):
            with patch("devenv_mcp.tools.venv.run_command") as mock_run:
                mock_run.side_effect = [python_check_result, venv_create_result]
                with patch("devenv_mcp.tools.venv._get_venv_info", return_value=mock_venv_info):
                    result = await tool_fn(
                        name="test-project",
                        path=None,
                        python_executable=None,
                        with_pip=True,
                        ctx=mock_mcp_context,
                    )

        assert result.name == "test-project"
        assert result.python_version == "3.11.5"
        assert result.is_valid is True
        # Check that the directory was created
        assert global_venvs.exists()

    @pytest.mark.asyncio
    async def test_creates_venv_in_custom_path(self, mock_mcp_context, tmp_path):
        """Test creating venv in a custom path."""
        tool_fn = self._get_tool_fn("devenv_venv_create")

        python_check_result = CommandResult(
            returncode=0,
            stdout="Python 3.11.5",
            stderr="",
            command="python --version",
        )
        venv_create_result = CommandResult(
            returncode=0,
            stdout="",
            stderr="",
            command="python -m venv",
        )

        mock_venv_info = VenvInfo(
            name=".venv",
            path=str(tmp_path / ".venv"),
            python_version="3.11.5",
            packages_count=0,
            is_valid=True,
        )

        with patch("devenv_mcp.tools.venv.run_command") as mock_run:
            mock_run.side_effect = [python_check_result, venv_create_result]
            with patch("devenv_mcp.tools.venv._get_venv_info", return_value=mock_venv_info):
                result = await tool_fn(
                    name=".venv",
                    path=str(tmp_path),
                    python_executable=None,
                    with_pip=True,
                    ctx=mock_mcp_context,
                )

        assert result.name == ".venv"
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_returns_existing_venv_if_already_exists(self, mock_mcp_context, tmp_path):
        """Test that existing valid venv is returned without recreating."""
        tool_fn = self._get_tool_fn("devenv_venv_create")

        # Create a fake existing venv
        existing_venv = tmp_path / "existing-venv"
        existing_venv.mkdir()

        mock_venv_info = VenvInfo(
            name="existing-venv",
            path=str(existing_venv),
            python_version="3.10.0",
            packages_count=5,
            is_valid=True,
        )

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch("devenv_mcp.tools.venv._get_venv_info", return_value=mock_venv_info):
                result = await tool_fn(
                    name="existing-venv",
                    path=str(tmp_path),
                    python_executable=None,
                    with_pip=True,
                    ctx=mock_mcp_context,
                )

        # Should return the existing venv info
        assert result.name == "existing-venv"
        assert result.python_version == "3.10.0"
        # Should have warned about existing venv
        mock_mcp_context.warning.assert_called()

    @pytest.mark.asyncio
    async def test_handles_python_not_found(self, mock_mcp_context, tmp_path):
        """Test error handling when python executable is not found."""
        tool_fn = self._get_tool_fn("devenv_venv_create")

        python_check_result = CommandResult(
            returncode=1,
            stdout="",
            stderr="Command not found: python3.99",
            command="python3.99 --version",
        )

        with patch("devenv_mcp.tools.venv.run_command", return_value=python_check_result):
            result = await tool_fn(
                name="test-venv",
                path=str(tmp_path),
                python_executable="python3.99",
                with_pip=True,
                ctx=mock_mcp_context,
            )

        assert result.is_valid is False
        assert "not found" in result.python_version.lower() or "error" in result.python_version.lower()

    @pytest.mark.asyncio
    async def test_handles_venv_creation_failure(self, mock_mcp_context, tmp_path):
        """Test error handling when venv creation fails."""
        tool_fn = self._get_tool_fn("devenv_venv_create")

        python_check_result = CommandResult(
            returncode=0,
            stdout="Python 3.11.5",
            stderr="",
            command="python --version",
        )
        venv_create_result = CommandResult(
            returncode=1,
            stdout="",
            stderr="Error: Failed to create venv",
            command="python -m venv",
        )

        with patch("devenv_mcp.tools.venv.run_command") as mock_run:
            mock_run.side_effect = [python_check_result, venv_create_result]
            result = await tool_fn(
                name="failed-venv",
                path=str(tmp_path),
                python_executable=None,
                with_pip=True,
                ctx=mock_mcp_context,
            )

        assert result.is_valid is False
        assert "Error" in result.python_version
        mock_mcp_context.error.assert_called()

    @pytest.mark.asyncio
    async def test_creates_venv_without_pip(self, mock_mcp_context, tmp_path):
        """Test creating venv without pip."""
        tool_fn = self._get_tool_fn("devenv_venv_create")

        python_check_result = CommandResult(
            returncode=0,
            stdout="Python 3.11.5",
            stderr="",
            command="python --version",
        )
        venv_create_result = CommandResult(
            returncode=0,
            stdout="",
            stderr="",
            command="python -m venv --without-pip",
        )

        mock_venv_info = VenvInfo(
            name="no-pip-venv",
            path=str(tmp_path / "no-pip-venv"),
            python_version="3.11.5",
            packages_count=0,
            is_valid=True,
        )

        with patch("devenv_mcp.tools.venv.run_command") as mock_run:
            mock_run.side_effect = [python_check_result, venv_create_result]
            with patch("devenv_mcp.tools.venv._get_venv_info", return_value=mock_venv_info):
                result = await tool_fn(
                    name="no-pip-venv",
                    path=str(tmp_path),
                    python_executable=None,
                    with_pip=False,
                    ctx=mock_mcp_context,
                )

        # Verify --without-pip was passed
        call_args = mock_run.call_args_list[1]  # Second call is venv creation
        command = call_args[0][0]  # First positional arg is the command list
        assert "--without-pip" in command

        assert result.is_valid is True


# =============================================================================
# Unit Tests - devenv_venv_delete tool
# =============================================================================


class TestDevenvVenvDelete:
    """Tests for the devenv_venv_delete MCP tool."""

    def _get_tool_fn(self, tool_name: str):
        """Helper to get a registered tool function."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.venv import register

        mcp = FastMCP("test")
        register(mcp)

        for tool in mcp._tool_manager._tools.values():
            if tool.name == tool_name:
                return tool.fn
        return None

    @pytest.mark.asyncio
    async def test_deletes_venv_by_path(self, mock_mcp_context, tmp_path):
        """Test deleting a venv by full path."""
        tool_fn = self._get_tool_fn("devenv_venv_delete")
        assert tool_fn is not None

        # Create a fake venv directory
        venv_path = tmp_path / "test-venv"
        venv_path.mkdir()
        (venv_path / "pyvenv.cfg").touch()

        mock_venv_info = VenvInfo(
            name="test-venv",
            path=str(venv_path),
            python_version="3.11.5",
            packages_count=5,
            is_valid=True,
        )

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch("devenv_mcp.tools.venv._get_venv_info", return_value=mock_venv_info):
                result = await tool_fn(
                    name=None,
                    path=str(venv_path),
                    ctx=mock_mcp_context,
                )

        assert "Successfully deleted" in result
        assert not venv_path.exists()

    @pytest.mark.asyncio
    async def test_deletes_venv_by_name(self, mock_mcp_context, tmp_path):
        """Test deleting a venv by name from ~/.venvs/."""
        tool_fn = self._get_tool_fn("devenv_venv_delete")

        # Create a fake global venvs directory
        global_venvs = tmp_path / ".venvs"
        global_venvs.mkdir()
        venv_path = global_venvs / "my-project"
        venv_path.mkdir()
        (venv_path / "pyvenv.cfg").touch()

        mock_venv_info = VenvInfo(
            name="my-project",
            path=str(venv_path),
            python_version="3.11.5",
            packages_count=10,
            is_valid=True,
        )

        with patch(
            "devenv_mcp.tools.venv.PlatformHelper.get_default_venv_location",
            return_value=global_venvs,
        ):
            with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
                with patch("devenv_mcp.tools.venv._get_venv_info", return_value=mock_venv_info):
                    result = await tool_fn(
                        name="my-project",
                        path=None,
                        ctx=mock_mcp_context,
                    )

        assert "Successfully deleted" in result
        assert not venv_path.exists()

    @pytest.mark.asyncio
    async def test_requires_name_or_path(self, mock_mcp_context):
        """Test that either name or path must be provided."""
        tool_fn = self._get_tool_fn("devenv_venv_delete")

        result = await tool_fn(
            name=None,
            path=None,
            ctx=mock_mcp_context,
        )

        assert "Error" in result
        assert "name" in result.lower() or "path" in result.lower()

    @pytest.mark.asyncio
    async def test_handles_nonexistent_venv(self, mock_mcp_context, tmp_path):
        """Test error when venv doesn't exist."""
        tool_fn = self._get_tool_fn("devenv_venv_delete")

        result = await tool_fn(
            name=None,
            path=str(tmp_path / "nonexistent-venv"),
            ctx=mock_mcp_context,
        )

        assert "Error" in result
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_rejects_non_venv_directory(self, mock_mcp_context, tmp_path):
        """Test safety check rejects directories that don't look like venvs."""
        tool_fn = self._get_tool_fn("devenv_venv_delete")

        # Create a regular directory (not a venv)
        regular_dir = tmp_path / "not-a-venv"
        regular_dir.mkdir()
        (regular_dir / "some-file.txt").touch()

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=False):
            result = await tool_fn(
                name=None,
                path=str(regular_dir),
                ctx=mock_mcp_context,
            )

        assert "Error" in result
        assert "not appear to be a virtual environment" in result
        # Directory should NOT be deleted
        assert regular_dir.exists()

    @pytest.mark.asyncio
    async def test_cancellation_preserves_venv(self, mock_mcp_context, tmp_path):
        """Test that cancelling the confirmation preserves the venv."""
        tool_fn = self._get_tool_fn("devenv_venv_delete")

        # Create a fake venv
        venv_path = tmp_path / "preserved-venv"
        venv_path.mkdir()
        (venv_path / "pyvenv.cfg").touch()

        # Mock elicit to return cancelled
        async def mock_elicit_cancel(message, schema):
            from unittest.mock import MagicMock

            result = MagicMock()
            result.action = "cancel"
            result.data = None
            return result

        mock_mcp_context.elicit = mock_elicit_cancel

        mock_venv_info = VenvInfo(
            name="preserved-venv",
            path=str(venv_path),
            python_version="3.11.5",
            packages_count=5,
            is_valid=True,
        )

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch("devenv_mcp.tools.venv._get_venv_info", return_value=mock_venv_info):
                result = await tool_fn(
                    name=None,
                    path=str(venv_path),
                    ctx=mock_mcp_context,
                )

        assert "cancelled" in result.lower()
        # Directory should still exist
        assert venv_path.exists()


# =============================================================================
# Unit Tests - devenv_venv_install tool
# =============================================================================


class TestDevenvVenvInstall:
    """Tests for the devenv_venv_install MCP tool."""

    def _get_tool_fn(self, tool_name: str):
        """Helper to get a registered tool function."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.venv import register

        mcp = FastMCP("test")
        register(mcp)

        for tool in mcp._tool_manager._tools.values():
            if tool.name == tool_name:
                return tool.fn
        return None

    @pytest.mark.asyncio
    async def test_installs_packages_by_name(self, mock_mcp_context, tmp_path):
        """Test installing packages into a venv by name."""
        tool_fn = self._get_tool_fn("devenv_venv_install")
        assert tool_fn is not None

        global_venvs = tmp_path / ".venvs"
        venv_path = global_venvs / "test-project"

        install_result = CommandResult(
            returncode=0,
            stdout="Successfully installed requests-2.28.0",
            stderr="",
            command="pip install requests",
        )

        with patch(
            "devenv_mcp.tools.venv.PlatformHelper.get_default_venv_location",
            return_value=global_venvs,
        ):
            with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
                with patch(
                    "devenv_mcp.tools.venv.PlatformHelper.get_venv_pip_path",
                    return_value=venv_path / "Scripts" / "pip.exe",
                ):
                    with patch("devenv_mcp.tools.venv.run_command", return_value=install_result):
                        result = await tool_fn(
                            packages=["requests"],
                            venv_path=None,
                            venv_name="test-project",
                            requirements_file=None,
                            upgrade=False,
                            ctx=mock_mcp_context,
                        )

        assert result.success is True
        assert "requests" in result.packages_installed

    @pytest.mark.asyncio
    async def test_installs_from_requirements_file(self, mock_mcp_context, tmp_path):
        """Test installing packages from requirements.txt."""
        tool_fn = self._get_tool_fn("devenv_venv_install")

        # Create a fake requirements file
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("flask>=2.0\nrequests\n")

        venv_path = tmp_path / ".venv"

        install_result = CommandResult(
            returncode=0,
            stdout="Successfully installed flask requests",
            stderr="",
            command="pip install -r requirements.txt",
        )

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_venv_pip_path",
                return_value=venv_path / "Scripts" / "pip.exe",
            ):
                with patch("devenv_mcp.tools.venv.run_command", return_value=install_result):
                    result = await tool_fn(
                        packages=[],
                        venv_path=str(venv_path),
                        venv_name=None,
                        requirements_file=str(req_file),
                        upgrade=False,
                        ctx=mock_mcp_context,
                    )

        assert result.success is True

    @pytest.mark.asyncio
    async def test_requires_venv_path_or_name(self, mock_mcp_context):
        """Test that venv_path or venv_name is required."""
        tool_fn = self._get_tool_fn("devenv_venv_install")

        result = await tool_fn(
            packages=["requests"],
            venv_path=None,
            venv_name=None,
            requirements_file=None,
            upgrade=False,
            ctx=mock_mcp_context,
        )

        assert result.success is False
        assert "Error" in result.message

    @pytest.mark.asyncio
    async def test_handles_installation_failure(self, mock_mcp_context, tmp_path):
        """Test handling of pip install failure."""
        tool_fn = self._get_tool_fn("devenv_venv_install")

        venv_path = tmp_path / ".venv"

        install_result = CommandResult(
            returncode=1,
            stdout="",
            stderr="ERROR: Could not find a version that satisfies the requirement nonexistent-pkg",
            command="pip install nonexistent-pkg",
        )

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_venv_pip_path",
                return_value=venv_path / "Scripts" / "pip.exe",
            ):
                with patch("devenv_mcp.tools.venv.run_command", return_value=install_result):
                    result = await tool_fn(
                        packages=["nonexistent-pkg"],
                        venv_path=str(venv_path),
                        venv_name=None,
                        requirements_file=None,
                        upgrade=False,
                        ctx=mock_mcp_context,
                    )

        assert result.success is False
        assert "Error" in result.message


# =============================================================================
# Unit Tests - devenv_venv_list_packages tool
# =============================================================================


class TestDevenvVenvListPackages:
    """Tests for the devenv_venv_list_packages MCP tool."""

    def _get_tool_fn(self, tool_name: str):
        """Helper to get a registered tool function."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.venv import register

        mcp = FastMCP("test")
        register(mcp)

        for tool in mcp._tool_manager._tools.values():
            if tool.name == tool_name:
                return tool.fn
        return None

    @pytest.mark.asyncio
    async def test_lists_packages(self, mock_mcp_context, tmp_path):
        """Test listing packages in a venv."""
        tool_fn = self._get_tool_fn("devenv_venv_list_packages")
        assert tool_fn is not None

        venv_path = tmp_path / ".venv"

        pip_list_result = CommandResult(
            returncode=0,
            stdout=json.dumps([
                {"name": "pip", "version": "23.0"},
                {"name": "setuptools", "version": "65.0"},
                {"name": "requests", "version": "2.28.0"},
            ]),
            stderr="",
            command="pip list --format=json",
        )

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_venv_pip_path",
                return_value=venv_path / "Scripts" / "pip.exe",
            ):
                with patch("devenv_mcp.tools.venv.run_command", return_value=pip_list_result):
                    result = await tool_fn(
                        venv_path=str(venv_path),
                        venv_name=None,
                        ctx=mock_mcp_context,
                    )

        assert len(result) == 3
        names = [pkg.name for pkg in result]
        assert "pip" in names
        assert "requests" in names

    @pytest.mark.asyncio
    async def test_returns_empty_for_invalid_venv(self, mock_mcp_context, tmp_path):
        """Test that invalid venv returns empty list."""
        tool_fn = self._get_tool_fn("devenv_venv_list_packages")

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=False):
            result = await tool_fn(
                venv_path=str(tmp_path / "nonexistent"),
                venv_name=None,
                ctx=mock_mcp_context,
            )

        assert result == []

    @pytest.mark.asyncio
    async def test_requires_venv_path_or_name(self, mock_mcp_context):
        """Test that venv_path or venv_name is required."""
        tool_fn = self._get_tool_fn("devenv_venv_list_packages")

        result = await tool_fn(
            venv_path=None,
            venv_name=None,
            ctx=mock_mcp_context,
        )

        assert result == []
        mock_mcp_context.error.assert_called()


# =============================================================================
# Unit Tests - devenv_venv_activate_info tool
# =============================================================================


class TestDevenvVenvActivateInfo:
    """Tests for the devenv_venv_activate_info MCP tool."""

    def _get_tool_fn(self, tool_name: str):
        """Helper to get a registered tool function."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.venv import register

        mcp = FastMCP("test")
        register(mcp)

        for tool in mcp._tool_manager._tools.values():
            if tool.name == tool_name:
                return tool.fn
        return None

    @pytest.mark.asyncio
    async def test_returns_activation_command(self, mock_mcp_context, tmp_path):
        """Test getting activation command for a venv."""
        tool_fn = self._get_tool_fn("devenv_venv_activate_info")
        assert tool_fn is not None

        venv_path = tmp_path / ".venv"
        venv_path.mkdir()

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_default_shell",
                return_value="bash",
            ):
                with patch(
                    "devenv_mcp.tools.venv.PlatformHelper.get_venv_activate_command",
                    return_value=f"source {venv_path}/bin/activate",
                ):
                    result = await tool_fn(
                        venv_path=str(venv_path),
                        venv_name=None,
                        shell=None,
                        ctx=mock_mcp_context,
                    )

        assert "activate" in result
        assert str(venv_path) in result

    @pytest.mark.asyncio
    async def test_returns_command_for_specific_shell(self, mock_mcp_context, tmp_path):
        """Test getting activation command for a specific shell."""
        tool_fn = self._get_tool_fn("devenv_venv_activate_info")

        venv_path = tmp_path / ".venv"
        venv_path.mkdir()

        with patch("devenv_mcp.tools.venv._is_valid_venv", return_value=True):
            with patch(
                "devenv_mcp.tools.venv.PlatformHelper.get_venv_activate_command",
                return_value=f"source {venv_path}/bin/activate.fish",
            ):
                result = await tool_fn(
                    venv_path=str(venv_path),
                    venv_name=None,
                    shell="fish",
                    ctx=mock_mcp_context,
                )

        assert "activate" in result

    @pytest.mark.asyncio
    async def test_returns_error_for_nonexistent_venv(self, mock_mcp_context, tmp_path):
        """Test error for nonexistent venv."""
        tool_fn = self._get_tool_fn("devenv_venv_activate_info")

        result = await tool_fn(
            venv_path=str(tmp_path / "nonexistent"),
            venv_name=None,
            shell=None,
            ctx=mock_mcp_context,
        )

        assert "Error" in result
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_requires_venv_path_or_name(self, mock_mcp_context):
        """Test that venv_path or venv_name is required."""
        tool_fn = self._get_tool_fn("devenv_venv_activate_info")

        result = await tool_fn(
            venv_path=None,
            venv_name=None,
            shell=None,
            ctx=mock_mcp_context,
        )

        assert "Error" in result


# =============================================================================
# Integration Tests (requires real venv)
# =============================================================================


@pytest.mark.integration
class TestVenvListIntegration:
    """Integration tests that use real virtual environments."""

    @pytest.mark.asyncio
    async def test_discovers_project_venv(self):
        """Test discovering the project's own .venv directory."""
        # This test uses the actual project's .venv
        project_root = Path(__file__).parent.parent
        venv_path = project_root / ".venv"

        if not venv_path.exists():
            pytest.skip("Project .venv not found")

        result = await _get_venv_info(venv_path)

        assert result.name == ".venv"
        assert result.is_valid is True
        assert result.python_version != "unknown"
        # Note: uv-managed venvs may not have pip, so packages_count can be 0
        assert result.packages_count >= 0

    @pytest.mark.asyncio
    async def test_full_tool_with_real_venv(self, mock_mcp_context):
        """Test the full tool with the project's real venv."""
        from mcp.server.fastmcp import FastMCP

        from devenv_mcp.tools.venv import register

        project_root = Path(__file__).parent.parent
        venv_path = project_root / ".venv"

        if not venv_path.exists():
            pytest.skip("Project .venv not found")

        mcp = FastMCP("test")
        register(mcp)

        tool_fn = None
        for tool in mcp._tool_manager._tools.values():
            if tool.name == "devenv_venv_list":
                tool_fn = tool.fn
                break

        result = await tool_fn(
            working_dir=str(project_root),
            include_global=False,
            name_pattern=None,
            ctx=mock_mcp_context,
        )

        assert len(result) >= 1
        venv_names = [v.name for v in result]
        assert ".venv" in venv_names

        # Find the .venv entry and verify its details
        project_venv = next(v for v in result if v.name == ".venv")
        assert project_venv.is_valid is True
        assert project_venv.python_version != "unknown"
