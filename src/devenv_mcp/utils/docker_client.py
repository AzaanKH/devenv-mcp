"""
Docker client wrapper with graceful handling when Docker is unavailable.

This wrapper:
- Connects to Docker daemon on startup (if available)
- Returns meaningful errors when Docker is not available
- Provides typed access to Docker operations
"""

import docker
from docker.errors import DockerException
from docker.models.containers import Container
from docker.models.images import Image

from devenv_mcp.utils.logging_config import get_logger

logger = get_logger("utils.docker_client")


class DockerUnavailableError(Exception):
    """Raised when Docker operations are attempted but Docker is not available."""
    
    def __init__(self, message: str = None):
        self.message = message or (
            "Docker is not available. Please ensure Docker Desktop is running "
            "or Docker Engine is installed and the daemon is started."
        )
        super().__init__(self.message)


class DockerClientWrapper:
    """
    Wrapper around Docker SDK client with graceful unavailability handling.
    
    Usage:
        wrapper = DockerClientWrapper()
        await wrapper.connect()
        
        if wrapper.is_available:
            containers = wrapper.list_containers()
        else:
            # Docker not available, handle gracefully
    """
    
    def __init__(self):
        self._client: docker.DockerClient | None = None
        self._is_available: bool = False
        self._unavailable_reason: str | None = None
    
    @property
    def is_available(self) -> bool:
        """Check if Docker is available and connected."""
        return self._is_available
    
    @property
    def unavailable_reason(self) -> str | None:
        """Get the reason why Docker is unavailable (if applicable)."""
        return self._unavailable_reason
    
    @property
    def client(self) -> docker.DockerClient:
        """
        Get the Docker client.
        
        Raises:
            DockerUnavailableError: If Docker is not available
        """
        if not self._is_available or self._client is None:
            raise DockerUnavailableError(self._unavailable_reason)
        return self._client
    
    async def connect(self) -> bool:
        """
        Attempt to connect to Docker daemon.
        
        Returns:
            True if connected successfully, False otherwise
        """
        try:
            logger.info("Attempting to connect to Docker daemon...")
            self._client = docker.from_env()
            
            # Verify connection by pinging
            self._client.ping()
            
            # Get version info
            version_info = self._client.version()
            docker_version = version_info.get("Version", "unknown")
            
            logger.info(f"Connected to Docker daemon (version {docker_version})")
            self._is_available = True
            self._unavailable_reason = None
            return True
            
        except DockerException as e:
            self._is_available = False
            self._unavailable_reason = str(e)
            logger.warning(f"Docker not available: {e}")
            return False
            
        except Exception as e:
            self._is_available = False
            self._unavailable_reason = f"Unexpected error connecting to Docker: {e}"
            logger.warning(self._unavailable_reason)
            return False
    
    async def close(self):
        """Close the Docker client connection."""
        if self._client is not None:
            try:
                self._client.close()
                logger.info("Docker client connection closed")
            except Exception as e:
                logger.warning(f"Error closing Docker client: {e}")
            finally:
                self._client = None
                self._is_available = False
    
    def require_docker(self) -> docker.DockerClient:
        """
        Get the Docker client, raising an error if unavailable.
        
        Use this in tools that require Docker to be available.
        
        Raises:
            DockerUnavailableError: If Docker is not available
        """
        return self.client
    
    # =========================================================================
    # Container operations
    # =========================================================================
    
    def list_containers(self, all: bool = False) -> list[Container]:
        """
        List Docker containers.
        
        Args:
            all: Include stopped containers
            
        Returns:
            List of Container objects
        """
        return self.client.containers.list(all=all)
    
    def get_container(self, container_id: str) -> Container:
        """
        Get a container by ID or name.
        
        Args:
            container_id: Container ID or name
            
        Returns:
            Container object
            
        Raises:
            docker.errors.NotFound: If container not found
        """
        return self.client.containers.get(container_id)
    
    # =========================================================================
    # Image operations
    # =========================================================================
    
    def list_images(self, all: bool = False) -> list[Image]:
        """
        List Docker images.
        
        Args:
            all: Include intermediate images
            
        Returns:
            List of Image objects
        """
        return self.client.images.list(all=all)
    
    def get_image(self, image_name: str) -> Image:
        """
        Get an image by name or ID.
        
        Args:
            image_name: Image name or ID
            
        Returns:
            Image object
        """
        return self.client.images.get(image_name)
    
    # =========================================================================
    # System operations
    # =========================================================================
    
    def get_disk_usage(self) -> dict:
        """Get Docker disk usage information."""
        return self.client.df()
    
    def get_info(self) -> dict:
        """Get Docker system information."""
        return self.client.info()
    
    def get_version(self) -> dict:
        """Get Docker version information."""
        return self.client.version()
    
    def prune_system(
        self, 
        containers: bool = True,
        images: bool = True,
        volumes: bool = False,  # Dangerous - data loss!
        networks: bool = True,
    ) -> dict:
        """
        Prune unused Docker resources.
        
        Args:
            containers: Prune stopped containers
            images: Prune unused images
            volumes: Prune unused volumes (DANGER: data loss!)
            networks: Prune unused networks
            
        Returns:
            Dict with pruned resource counts and space reclaimed
        """
        results = {}
        
        if containers:
            results["containers"] = self.client.containers.prune()
        if images:
            results["images"] = self.client.images.prune()
        if volumes:
            results["volumes"] = self.client.volumes.prune()
        if networks:
            results["networks"] = self.client.networks.prune()
        
        return results
