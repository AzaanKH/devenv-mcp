"""
Virtual environment management tools for DevEnv MCP.

These tools provide Python venv creation, management, and package operations.
All tools are prefixed with `devenv_venv_` for namespacing.

Implemented tools:
- devenv_venv_list [readOnly: true]
- devenv_venv_create [destructive: false]
- devenv_venv_delete [destructive: true]
- devenv_venv_install [destructive: false]
- devenv_venv_list_packages [readOnly: true]
- devenv_venv_activate_info [readOnly: true]
"""

import asyncio
import fnmatch
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from pydantic import BaseModel, Field

from devenv_mcp.utils import PlatformHelper, get_logger, run_command

if TYPE_CHECKING:
    from devenv_mcp.server import AppContext

logger = get_logger("tools.venv")


# =============================================================================
# Data Models
# =============================================================================


class VenvInfo(BaseModel):
    """Information about a Python virtual environment."""

    name: str = Field(description="Name of the virtual environment (directory name)")
    path: str = Field(description="Full absolute path to the venv directory")
    python_version: str = Field(
        description="Python version (e.g., '3.11.5') or 'unknown' if broken"
    )
    packages_count: int = Field(description="Number of installed packages")
    is_valid: bool = Field(description="Whether the venv is functional")


class PackageInfo(BaseModel):
    """Information about an installed Python package."""

    name: str = Field(description="Package name")
    version: str = Field(description="Installed version")


class InstallResult(BaseModel):
    """Result of a package installation operation."""

    success: bool = Field(description="Whether the installation succeeded")
    venv_name: str = Field(description="Name of the venv")
    packages_installed: list[str] = Field(description="List of packages that were installed")
    message: str = Field(description="Status message or error details")


# =============================================================================
# Helper Functions
# =============================================================================


def _is_valid_venv(venv_path: Path) -> bool:
    """Check if a directory is a valid virtual environment."""
    python_path = PlatformHelper.get_venv_python_path(venv_path)
    return python_path.exists()


async def _get_venv_info(venv_path: Path) -> VenvInfo:
    """
    Gather information for a single virtual environment.

    Runs python --version and pip list in parallel for efficiency.
    """
    name = venv_path.name
    path_str = str(venv_path)

    python_path = PlatformHelper.get_venv_python_path(venv_path)
    pip_path = PlatformHelper.get_venv_pip_path(venv_path)

    # Check if venv is valid first
    if not python_path.exists():
        return VenvInfo(
            name=name,
            path=path_str,
            python_version="unknown",
            packages_count=0,
            is_valid=False,
        )

    # Run both commands in parallel
    version_task = run_command(
        [str(python_path), "--version"],
        timeout=10.0,
    )
    packages_task = run_command(
        [str(pip_path), "list", "--format=json"],
        timeout=30.0,
    )

    try:
        version_result, packages_result = await asyncio.gather(
            version_task, packages_task, return_exceptions=True
        )
    except Exception as e:
        logger.warning(f"Error getting venv info for {venv_path}: {e}")
        return VenvInfo(
            name=name,
            path=path_str,
            python_version="unknown",
            packages_count=0,
            is_valid=False,
        )

    # Parse Python version
    python_version = "unknown"
    if not isinstance(version_result, Exception) and version_result.success:
        # Output is like "Python 3.11.5"
        version_output = version_result.stdout.strip()
        if version_output.startswith("Python "):
            python_version = version_output[7:]  # Remove "Python " prefix

    # Parse package count
    packages_count = 0
    if not isinstance(packages_result, Exception) and packages_result.success:
        try:
            packages = json.loads(packages_result.stdout)
            packages_count = len(packages)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse pip list output for {venv_path}")

    # Determine if valid (both commands succeeded)
    is_valid = (
        not isinstance(version_result, Exception)
        and version_result.success
        and python_version != "unknown"
    )

    return VenvInfo(
        name=name,
        path=path_str,
        python_version=python_version,
        packages_count=packages_count,
        is_valid=is_valid,
    )


def _discover_venvs(
    working_dir: Path,
    include_global: bool,
    name_pattern: str | None,
) -> list[Path]:
    """
    Discover virtual environments in the specified locations.

    Args:
        working_dir: Directory to search for local venvs (.venv, venv)
        include_global: Whether to include ~/.venvs/
        name_pattern: Optional glob pattern to filter by name

    Returns:
        List of paths to valid venv directories
    """
    discovered = []

    # Check local venvs in working_dir
    local_venv_names = ["venv", ".venv"]
    for venv_name in local_venv_names:
        venv_path = working_dir / venv_name
        if venv_path.exists() and venv_path.is_dir() and _is_valid_venv(venv_path):
            discovered.append(venv_path)

    # Check global venvs in ~/.venvs/
    if include_global:
        global_venvs_dir = PlatformHelper.get_default_venv_location()
        if global_venvs_dir.exists() and global_venvs_dir.is_dir():
            for child in global_venvs_dir.iterdir():
                if child.is_dir() and _is_valid_venv(child):
                    discovered.append(child)

    # Apply name pattern filter if specified
    if name_pattern:
        discovered = [
            venv_path
            for venv_path in discovered
            if fnmatch.fnmatch(venv_path.name, name_pattern)
        ]

    return discovered


# =============================================================================
# Tool Registration
# =============================================================================


def register(mcp: FastMCP):
    """Register all venv tools with the MCP server."""

    # =========================================================================
    # devenv_venv_list - List virtual environments
    # [readOnly: true]
    # =========================================================================
    @mcp.tool()
    async def devenv_venv_list(
        working_dir: str = ".",
        include_global: bool = True,
        name_pattern: str = None,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> list[VenvInfo]:
        """
        List Python virtual environments.

        Discovers venvs in the working directory (./venv, ./.venv) and optionally
        in the global ~/.venvs/ directory. Returns details including Python version
        and installed package count.

        Args:
            working_dir: Directory to search for local venvs (default: current directory)
            include_global: Include virtual environments from ~/.venvs/ (default: True)
            name_pattern: Filter venvs by name using glob pattern (e.g., "project-*")

        Returns:
            List of VenvInfo with name, path, python_version, packages_count, is_valid

        Example:
            - List all venvs: devenv_venv_list()
            - Local only: devenv_venv_list(include_global=False)
            - Filter by name: devenv_venv_list(name_pattern="my-*")
        """
        # Resolve working directory
        work_path = Path(working_dir).expanduser().resolve()

        if not work_path.exists():
            await ctx.warning(f"Working directory does not exist: {work_path}")
            work_path = Path.cwd()

        await ctx.info(f"Searching for venvs in {work_path}")
        if include_global:
            global_path = PlatformHelper.get_default_venv_location()
            await ctx.info(f"Also searching in {global_path}")

        # Discover venvs
        venv_paths = _discover_venvs(work_path, include_global, name_pattern)

        if not venv_paths:
            await ctx.info("No virtual environments found")
            return []

        await ctx.info(f"Found {len(venv_paths)} venv(s), gathering details...")

        # Gather info for all venvs in parallel
        venv_infos = await asyncio.gather(*[_get_venv_info(path) for path in venv_paths])

        # Log summary
        valid_count = sum(1 for v in venv_infos if v.is_valid)
        await ctx.info(f"Retrieved info for {len(venv_infos)} venv(s) ({valid_count} valid)")

        return list(venv_infos)

    # =========================================================================
    # devenv_venv_create - Create a new virtual environment
    # [destructive: false]
    # =========================================================================
    @mcp.tool()
    async def devenv_venv_create(
        name: str,
        path: str = None,
        python_executable: str = None,
        with_pip: bool = True,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> VenvInfo:
        """
        Create a new Python virtual environment.

        Creates a venv using `python -m venv`. By default, creates in ~/.venvs/{name}.
        You can specify a custom path to create the venv elsewhere.

        Args:
            name: Name for the virtual environment (used as directory name)
            path: Parent directory for the venv (default: ~/.venvs/)
            python_executable: Python executable to use (default: system python)
            with_pip: Include pip in the venv (default: True)

        Returns:
            VenvInfo with details of the created venv

        Example:
            - Create in default location: devenv_venv_create(name="myproject")
            - Create in current dir: devenv_venv_create(name=".venv", path=".")
            - Use specific Python: devenv_venv_create(name="py311", python_executable="python3.11")
        """
        # Determine the target path
        if path is None:
            parent_dir = PlatformHelper.get_default_venv_location()
        else:
            parent_dir = Path(path).expanduser().resolve()

        target_path = parent_dir / name

        # Ensure parent directory exists
        if not parent_dir.exists():
            await ctx.info(f"Creating directory: {parent_dir}")
            parent_dir.mkdir(parents=True, exist_ok=True)

        # Check if venv already exists
        if target_path.exists():
            if _is_valid_venv(target_path):
                await ctx.warning(f"Venv already exists at {target_path}")
                return await _get_venv_info(target_path)
            else:
                return VenvInfo(
                    name=name,
                    path=str(target_path),
                    python_version="unknown",
                    packages_count=0,
                    is_valid=False,
                )

        # Determine which Python to use
        if python_executable is None:
            python_executable = "python"

        # Check if the Python executable exists
        python_check = await run_command(
            [python_executable, "--version"],
            timeout=10.0,
        )
        if not python_check.success:
            return VenvInfo(
                name=name,
                path=str(target_path),
                python_version=f"Error: Python executable '{python_executable}' not found",
                packages_count=0,
                is_valid=False,
            )

        # Build the venv creation command
        venv_cmd = [python_executable, "-m", "venv"]
        if not with_pip:
            venv_cmd.append("--without-pip")
        venv_cmd.append(str(target_path))

        await ctx.info(f"Creating venv at {target_path}...")

        # Create the venv
        result = await run_command(
            venv_cmd,
            timeout=120.0,  # venv creation can take a while, especially with pip
        )

        if not result.success:
            error_msg = result.stderr or result.stdout or "Unknown error"
            await ctx.error(f"Failed to create venv: {error_msg}")
            return VenvInfo(
                name=name,
                path=str(target_path),
                python_version=f"Error: {error_msg}",
                packages_count=0,
                is_valid=False,
            )

        await ctx.info(f"Successfully created venv: {name}")

        # Return info about the created venv
        return await _get_venv_info(target_path)

    # =========================================================================
    # devenv_venv_delete - Delete a virtual environment
    # [destructive: true] - Requires confirmation
    # =========================================================================
    @mcp.tool()
    async def devenv_venv_delete(
        name: str = None,
        path: str = None,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> str:
        """
        Delete a Python virtual environment. This action is IRREVERSIBLE.

        You must provide either a name (for venvs in ~/.venvs/) or a full path.
        This will permanently delete the entire venv directory.

        Args:
            name: Name of the venv in ~/.venvs/ to delete
            path: Full path to the venv directory to delete

        Returns:
            Success or error message

        Example:
            - Delete by name: devenv_venv_delete(name="old-project")
            - Delete by path: devenv_venv_delete(path="/path/to/project/.venv")

        ⚠️ WARNING: This is a destructive operation that cannot be undone.
        """
        # Determine the target path
        if path is not None:
            target_path = Path(path).expanduser().resolve()
        elif name is not None:
            target_path = PlatformHelper.get_default_venv_location() / name
        else:
            return "Error: Must provide either 'name' or 'path'"

        # Check if the venv exists
        if not target_path.exists():
            return f"Error: Venv not found at {target_path}"

        # Verify it looks like a venv (safety check)
        if not _is_valid_venv(target_path):
            # Check if it has common venv markers even if python is missing
            has_venv_markers = (
                (target_path / "pyvenv.cfg").exists()
                or (target_path / "Scripts").exists()
                or (target_path / "bin").exists()
            )
            if not has_venv_markers:
                return f"Error: {target_path} does not appear to be a virtual environment"

        # Get venv info for confirmation message
        venv_info = await _get_venv_info(target_path)

        # Request confirmation for destructive operation
        from pydantic import BaseModel as ConfirmModel

        class ConfirmDelete(ConfirmModel):
            confirm: bool = Field(description="Set to true to confirm deletion")

        confirm_msg = f"Are you sure you want to delete the virtual environment '{target_path.name}'?"
        if venv_info.is_valid:
            confirm_msg += f"\n  Python: {venv_info.python_version}"
            confirm_msg += f"\n  Packages: {venv_info.packages_count}"
        confirm_msg += "\n\nThis will permanently delete the entire directory. This cannot be undone."

        result = await ctx.elicit(
            message=confirm_msg,
            schema=ConfirmDelete,
        )

        # Check response
        if result.action != "accept" or not result.data or not result.data.confirm:
            return "Deletion cancelled"

        # Proceed with deletion
        try:
            await ctx.info(f"Deleting venv at {target_path}...")
            shutil.rmtree(target_path)
            await ctx.info(f"Successfully deleted venv: {target_path.name}")
            return f"Successfully deleted virtual environment: {target_path.name}"
        except PermissionError as e:
            await ctx.error(f"Permission denied: {e}")
            return f"Error: Permission denied - could not delete {target_path}"
        except Exception as e:
            await ctx.error(f"Failed to delete venv: {e}")
            return f"Error: Failed to delete venv - {e}"

    # =========================================================================
    # devenv_venv_install - Install packages into a venv
    # [destructive: false]
    # =========================================================================
    @mcp.tool()
    async def devenv_venv_install(
        packages: list[str],
        venv_path: str = None,
        venv_name: str = None,
        requirements_file: str = None,
        upgrade: bool = False,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> InstallResult:
        """
        Install packages into a Python virtual environment.

        You must provide either venv_path or venv_name (for ~/.venvs/).
        Specify packages as a list, or use requirements_file for a requirements.txt.

        Args:
            packages: List of packages to install (e.g., ["requests", "flask>=2.0"])
            venv_path: Full path to the venv
            venv_name: Name of venv in ~/.venvs/
            requirements_file: Path to requirements.txt file
            upgrade: Upgrade packages if already installed

        Returns:
            InstallResult with success status and details

        Example:
            - Install packages: devenv_venv_install(packages=["requests", "flask"], venv_name="myproject")
            - From requirements: devenv_venv_install(packages=[], venv_path="./.venv", requirements_file="requirements.txt")
        """
        # Determine the target venv path
        if venv_path is not None:
            target_path = Path(venv_path).expanduser().resolve()
        elif venv_name is not None:
            target_path = PlatformHelper.get_default_venv_location() / venv_name
        else:
            return InstallResult(
                success=False,
                venv_name="unknown",
                packages_installed=[],
                message="Error: Must provide either 'venv_path' or 'venv_name'",
            )

        # Verify venv exists
        if not _is_valid_venv(target_path):
            return InstallResult(
                success=False,
                venv_name=target_path.name,
                packages_installed=[],
                message=f"Error: No valid venv found at {target_path}",
            )

        pip_path = PlatformHelper.get_venv_pip_path(target_path)

        # Build pip install command
        pip_cmd = [str(pip_path), "install"]
        if upgrade:
            pip_cmd.append("--upgrade")

        # Add requirements file if specified
        if requirements_file:
            req_path = Path(requirements_file).expanduser().resolve()
            if not req_path.exists():
                return InstallResult(
                    success=False,
                    venv_name=target_path.name,
                    packages_installed=[],
                    message=f"Error: Requirements file not found: {req_path}",
                )
            pip_cmd.extend(["-r", str(req_path)])

        # Add individual packages
        pip_cmd.extend(packages)

        # Nothing to install?
        if not packages and not requirements_file:
            return InstallResult(
                success=False,
                venv_name=target_path.name,
                packages_installed=[],
                message="Error: No packages or requirements file specified",
            )

        await ctx.info(f"Installing packages into {target_path.name}...")

        # Run pip install
        result = await run_command(
            pip_cmd,
            timeout=300.0,  # Package installation can be slow
        )

        if result.success:
            await ctx.info("Installation completed successfully")
            return InstallResult(
                success=True,
                venv_name=target_path.name,
                packages_installed=packages,
                message=result.stdout or "Packages installed successfully",
            )
        else:
            await ctx.error(f"Installation failed: {result.stderr}")
            return InstallResult(
                success=False,
                venv_name=target_path.name,
                packages_installed=[],
                message=f"Error: {result.stderr or result.stdout}",
            )

    # =========================================================================
    # devenv_venv_list_packages - List installed packages
    # [readOnly: true]
    # =========================================================================
    @mcp.tool()
    async def devenv_venv_list_packages(
        venv_path: str = None,
        venv_name: str = None,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> list[PackageInfo]:
        """
        List installed packages in a Python virtual environment.

        Args:
            venv_path: Full path to the venv
            venv_name: Name of venv in ~/.venvs/

        Returns:
            List of PackageInfo with name and version for each package

        Example:
            - By path: devenv_venv_list_packages(venv_path="./.venv")
            - By name: devenv_venv_list_packages(venv_name="myproject")
        """
        # Determine the target venv path
        if venv_path is not None:
            target_path = Path(venv_path).expanduser().resolve()
        elif venv_name is not None:
            target_path = PlatformHelper.get_default_venv_location() / venv_name
        else:
            await ctx.error("Must provide either 'venv_path' or 'venv_name'")
            return []

        # Verify venv exists
        if not _is_valid_venv(target_path):
            await ctx.error(f"No valid venv found at {target_path}")
            return []

        pip_path = PlatformHelper.get_venv_pip_path(target_path)

        # Run pip list
        result = await run_command(
            [str(pip_path), "list", "--format=json"],
            timeout=30.0,
        )

        if not result.success:
            await ctx.error(f"Failed to list packages: {result.stderr}")
            return []

        # Parse JSON output
        try:
            packages_data = json.loads(result.stdout)
            packages = [
                PackageInfo(name=pkg["name"], version=pkg["version"])
                for pkg in packages_data
            ]
            await ctx.info(f"Found {len(packages)} packages in {target_path.name}")
            return packages
        except json.JSONDecodeError as e:
            await ctx.error(f"Failed to parse pip output: {e}")
            return []

    # =========================================================================
    # devenv_venv_activate_info - Get activation command
    # [readOnly: true]
    # =========================================================================
    @mcp.tool()
    async def devenv_venv_activate_info(
        venv_path: str = None,
        venv_name: str = None,
        shell: str = None,
        ctx: Context[ServerSession, "AppContext"] = None,
    ) -> str:
        """
        Get the activation command for a Python virtual environment.

        Returns the shell command needed to activate the venv for the user's
        platform and shell.

        Args:
            venv_path: Full path to the venv
            venv_name: Name of venv in ~/.venvs/
            shell: Shell type (bash, zsh, fish, powershell, cmd). Auto-detected if not specified.

        Returns:
            Activation command string

        Example:
            - By path: devenv_venv_activate_info(venv_path="./.venv")
            - Specific shell: devenv_venv_activate_info(venv_name="myproject", shell="fish")
        """
        # Determine the target venv path
        if venv_path is not None:
            target_path = Path(venv_path).expanduser().resolve()
        elif venv_name is not None:
            target_path = PlatformHelper.get_default_venv_location() / venv_name
        else:
            return "Error: Must provide either 'venv_path' or 'venv_name'"

        # Verify venv exists
        if not target_path.exists():
            return f"Error: Venv not found at {target_path}"

        if not _is_valid_venv(target_path):
            return f"Error: {target_path} does not appear to be a valid venv"

        # Get activation command for the specified or default shell
        shell_type = shell or PlatformHelper.get_default_shell()
        activate_cmd = PlatformHelper.get_venv_activate_command(target_path, shell_type)

        await ctx.info(f"Activation command for {target_path.name} ({shell_type})")

        return activate_cmd

    logger.info("Venv tools registered")
