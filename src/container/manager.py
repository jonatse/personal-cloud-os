"""Container Manager - Manages the Linux OS container."""
import asyncio
import logging
import os
import uuid
from typing import Optional, Dict, List
from dataclasses import dataclass
from enum import Enum
import threading
import subprocess

from src.core.events import Event

logger = logging.getLogger(__name__)


class ContainerState(Enum):
    """Container states."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class ContainerInfo:
    """Container information."""
    id: str
    name: str
    image: str
    state: str
    created: str
    ports: Dict[str, str] = None
    
    def __post_init__(self):
        if self.ports is None:
            self.ports = {}


class ContainerManager:
    """
    Manages the Linux OS container.
    
    Provides your Alpine/Debian environment with your files,
    configs, terminal, and all your tools. Runs always like
    a background service.
    """
    
    def __init__(self, config, event_bus):
        """Initialize container manager."""
        self.config = config
        self.event_bus = event_bus
        
        self._container_id: Optional[str] = None
        self._state = ContainerState.STOPPED
        self._lock = threading.Lock()
        
        # Container settings
        self._image = config.get("container.image", "alpine:latest")
        self._container_name = config.get("container.name", "personal-cloud-os")
        self._auto_start = config.get("container.auto_start", True)
        
        # Working directory for container files
        self._work_dir = os.path.expanduser("~/.local/share/pcos/container")
        os.makedirs(self._work_dir, exist_ok=True)
    
    async def start(self):
        """Start the container."""
        if self._state == ContainerState.RUNNING:
            logger.warning("Container already running")
            return
        
        logger.info("Starting container...")
        self._set_state(ContainerState.STARTING)
        
        try:
            # Check if Docker is available
            if not await self._check_docker():
                logger.error("Docker is not available")
                self._set_state(ContainerState.ERROR)
                return
            
            # Check if container already exists
            existing = await self._get_container()
            if existing:
                logger.info(f"Container already exists: {existing.id}")
                self._container_id = existing.id
                
                # Start existing container
                await self._start_container()
            else:
                # Create and start new container
                await self._create_container()
            
            self._set_state(ContainerState.RUNNING)
            logger.info("Container started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start container: {e}")
            self._set_state(ContainerState.ERROR)
            raise
    
    async def stop(self):
        """Stop the container."""
        if self._state == ContainerState.STOPPED:
            return
        
        logger.info("Stopping container...")
        self._set_state(ContainerState.STOPPING)
        
        try:
            if self._container_id:
                await self._stop_container()
            
            self._set_state(ContainerState.STOPPED)
            logger.info("Container stopped")
            
        except Exception as e:
            logger.error(f"Failed to stop container: {e}")
            self._set_state(ContainerState.ERROR)
            raise
    
    async def restart(self):
        """Restart the container."""
        await self.stop()
        await asyncio.sleep(2)
        await self.start()
    
    async def _check_docker(self) -> bool:
        """Check if Docker is available."""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    async def _get_container(self) -> Optional[ContainerInfo]:
        """Get existing container info."""
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--filter", f"name={self._container_name}", "--format", "{{.ID}}"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                container_id = result.stdout.strip()
                return ContainerInfo(
                    id=container_id,
                    name=self._container_name,
                    image=self._image,
                    state="existing",
                    created=""
                )
        except Exception as e:
            logger.debug(f"Error getting container: {e}")
        return None
    
    async def _create_container(self):
        """Create a new container."""
        logger.info(f"Creating container from image: {self._image}")
        
        # Mount points for persisting data
        home_mount = f"{self._work_dir}/home:/root"
        config_mount = f"{self._work_dir}/config:/config"
        
        cmd = [
            "docker", "create",
            "--name", self._container_name,
            "-it",
            "-v", home_mount,
            "-v", config_mount,
            "--hostname", "personal-cloud-os",
            self._image,
            "/bin/sh"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to create container: {result.stderr}")
        
        self._container_id = result.stdout.strip()
        logger.info(f"Container created: {self._container_id}")
        
        # Start the container
        await self._start_container()
    
    async def _start_container(self):
        """Start the container."""
        if not self._container_id:
            return
        
        result = subprocess.run(
            ["docker", "start", self._container_id],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start container: {result.stderr}")
        
        logger.info("Container started")
    
    async def _stop_container(self):
        """Stop the container."""
        if not self._container_id:
            return
        
        result = subprocess.run(
            ["docker", "stop", self._container_id],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            logger.warning(f"Failed to stop container gracefully: {result.stderr}")
            # Force kill
            subprocess.run(
                ["docker", "kill", self._container_id],
                capture_output=True
            )
    
    async def execute(self, command: List[str]) -> tuple:
        """Execute a command in the container."""
        if not self._container_id or self._state != ContainerState.RUNNING:
            raise RuntimeError("Container not running")
        
        cmd = ["docker", "exec", "-i", self._container_name] + command
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        return result.stdout, result.stderr, result.returncode
    
    async def get_shell(self):
        """Get an interactive shell in the container."""
        if not self._container_id or self._state != ContainerState.RUNNING:
            raise RuntimeError("Container not running")
        
        # This would attach to the container's shell
        # For now, return exec command
        return ["docker", "exec", "-it", self._container_name, "/bin/sh"]
    
    def _set_state(self, state: ContainerState):
        """Set container state."""
        with self._lock:
            self._state = state
        
        # Publish state change event
        asyncio.create_task(self.event_bus.publish(Event(
            type=f"container.{state.value}",
            data={"container_id": self._container_id, "state": state.value},
            source="container"
        )))
    
    def get_state(self) -> ContainerState:
        """Get current container state."""
        return self._state
    
    def is_running(self) -> bool:
        """Check if container is running."""
        return self._state == ContainerState.RUNNING
    
    @property
    def container_id(self) -> Optional[str]:
        """Get container ID."""
        return self._container_id
    
    @property
    def work_dir(self) -> str:
        """Get container work directory."""
        return self._work_dir
