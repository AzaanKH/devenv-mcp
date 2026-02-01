"""
Cross-platform utilities for handling OS-specific differences.

Supports Windows, macOS, and Linux with appropriate path handling,
executable locations, and shell commands.
"""

import os
import platform
import shutil
from pathlib import Path
from typing import Literal

PlatformType = Literal["windows", "macos", "linux"]
ShellType = Literal["bash", "zsh", "fish", "powershell", "cmd"]


class PlatformHelper:
    """Handle cross-platform differences for development tools."""
    
    @staticmethod
    def get_platform() -> PlatformType:
        """
        Get the current platform.
        
        Returns:
            'windows', 'macos', or 'linux'
        """
        system = platform.system().lower()
        if system == "darwin":
            return "macos"
        elif system == "windows":
            return "windows"
        return "linux"
    
    @staticmethod
    def get_default_shell() -> ShellType:
        """Get the default shell for the current platform."""
        if PlatformHelper.get_platform() == "windows":
            return "powershell"
        
        # Check SHELL environment variable on Unix
        shell_path = os.environ.get("SHELL", "/bin/bash")
        shell_name = Path(shell_path).name
        
        if shell_name in ("bash", "zsh", "fish"):
            return shell_name  # type: ignore
        return "bash"
    
    @staticmethod
    def get_home_directory() -> Path:
        """Get the user's home directory."""
        return Path.home()
    
    @staticmethod
    def get_venv_python_path(venv_path: str | Path) -> Path:
        """
        Get the path to the Python executable in a virtual environment.
        
        Args:
            venv_path: Path to the virtual environment
            
        Returns:
            Path to the python executable
        """
        venv_path = Path(venv_path).expanduser().resolve()
        
        if PlatformHelper.get_platform() == "windows":
            return venv_path / "Scripts" / "python.exe"
        return venv_path / "bin" / "python"
    
    @staticmethod
    def get_venv_pip_path(venv_path: str | Path) -> Path:
        """
        Get the path to pip in a virtual environment.
        
        Args:
            venv_path: Path to the virtual environment
            
        Returns:
            Path to the pip executable
        """
        venv_path = Path(venv_path).expanduser().resolve()
        
        if PlatformHelper.get_platform() == "windows":
            return venv_path / "Scripts" / "pip.exe"
        return venv_path / "bin" / "pip"
    
    @staticmethod
    def get_venv_activate_command(venv_path: str | Path, shell: ShellType = None) -> str:
        """
        Get the activation command for a virtual environment.
        
        Args:
            venv_path: Path to the virtual environment
            shell: Shell type (auto-detected if not specified)
            
        Returns:
            Command string to activate the environment
        """
        venv_path = Path(venv_path).expanduser().resolve()
        shell = shell or PlatformHelper.get_default_shell()
        
        if PlatformHelper.get_platform() == "windows":
            if shell == "powershell":
                return f"{venv_path}\\Scripts\\Activate.ps1"
            else:  # cmd
                return f"{venv_path}\\Scripts\\activate.bat"
        else:  # macOS/Linux
            if shell == "fish":
                return f"source {venv_path}/bin/activate.fish"
            else:  # bash/zsh
                return f"source {venv_path}/bin/activate"
    
    @staticmethod
    def get_default_venv_location() -> Path:
        """
        Get the default location for storing virtual environments.
        
        Returns:
            Path to default venv directory (e.g., ~/.venvs)
        """
        return PlatformHelper.get_home_directory() / ".venvs"
    
    @staticmethod
    def find_executable(name: str) -> str | None:
        """
        Find an executable in PATH.
        
        Args:
            name: Executable name (e.g., 'docker', 'python')
            
        Returns:
            Full path to executable, or None if not found
        """
        return shutil.which(name)
    
    @staticmethod
    def is_executable_available(name: str) -> bool:
        """Check if an executable is available in PATH."""
        return PlatformHelper.find_executable(name) is not None
    
    @staticmethod
    def get_path_separator() -> str:
        """Get the PATH environment variable separator."""
        if PlatformHelper.get_platform() == "windows":
            return ";"
        return ":"
    
    @staticmethod
    def normalize_path(path: str | Path) -> Path:
        """
        Normalize a path for the current platform.
        
        Expands ~ and resolves to absolute path.
        """
        return Path(path).expanduser().resolve()
    
    @staticmethod
    def to_posix_path(path: str | Path) -> str:
        """
        Convert a path to POSIX format (forward slashes).
        
        Useful for Docker and other tools that expect POSIX paths.
        """
        return Path(path).as_posix()
    
    @staticmethod
    def get_temp_directory() -> Path:
        """Get the system temp directory."""
        import tempfile
        return Path(tempfile.gettempdir())


# Convenience instance for direct usage
platform_helper = PlatformHelper()
