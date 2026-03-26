"""Container Manager - Chroot-based Alpine Linux container."""
import asyncio
import logging
import os
import sys
import uuid
import shutil
import stat
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from enum import Enum
import threading
import subprocess
import socket
import select

from core.events import Event

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
    rootfs_path: str
    data_path: str
    home_path: str
    state: str
    version: str = "3.20"


class ContainerManager:
    """
    Manages the Alpine Linux container via chroot.
    
    This is your "OS instance" - like Urbit's ship:
    - All data lives in container/data/
    - Syncing = syncing the data folder
    - All modifications persist in the container
    """
    
    def __init__(self, config, event_bus):
        """Initialize container manager."""
        self.config = config
        self.event_bus = event_bus
        
        self._state = ContainerState.STOPPED
        self._lock = threading.Lock()
        self._shell_socket = None
        self._shell_process = None
        
        # Paths
        self._src_dir = os.path.dirname(os.path.abspath(__file__))
        self._rootfs_src = os.path.join(self._src_dir, "rootfs")
        
        # Container paths (in user's data directory)
        self._container_base = os.path.expanduser("~/.local/share/pcos/container")
        self._rootfs_path = os.path.join(self._container_base, "rootfs")
        self._data_path = os.path.join(self._container_base, "data")
        self._home_path = os.path.join(self._container_base, "home")
        self._config_path = os.path.join(self._container_base, "config")
        
        # Ensure directories exist
        for path in [self._container_base, self._data_path, self._home_path, self._config_path]:
            os.makedirs(path, exist_ok=True)
        
        # Setup rootfs (copy from source if needed)
        self._setup_rootfs()
        
        # Container ID (based on RNS identity hash - like Urbit's ship ID)
        self._container_id = self._get_container_id()
        
        logger.info(f"Container Manager initialized. ID: {self._container_id}")
    
    def _get_container_id(self) -> str:
        """Get unique container ID from system."""
        try:
            # Try to use machine-id for unique ID
            with open("/etc/machine-id", "r") as f:
                return f.read().strip()[:16]
        except:
            return uuid.uuid4().hex[:16]
    
    def _setup_rootfs(self):
        """Setup rootfs - copy from source or use existing."""
        if os.path.exists(self._rootfs_path):
            logger.debug("Using existing rootfs")
            return
        
        logger.info(f"Setting up rootfs from {self._rootfs_src}")
        
        # Copy rootfs to container directory
        shutil.copytree(self._rootfs_src, self._rootfs_path, symlinks=True)
        
        # Create required directories
        for d in ["proc", "sys", "dev", "run"]:
            os.makedirs(os.path.join(self._rootfs_path, d), exist_ok=True)
        
        # Ensure data and home directories are accessible
        os.makedirs(self._data_path, exist_ok=True)
        os.makedirs(self._home_path, exist_ok=True)
        
        # Create /data symlink in rootfs pointing to data folder
        data_link = os.path.join(self._rootfs_path, "data")
        if not os.path.exists(data_link):
            os.symlink(self._data_path, data_link)
        
        # Create /home symlink
        home_link = os.path.join(self._rootfs_path, "home")
        if not os.path.exists(home_link):
            os.symlink(self._home_path, home_link)
        
        logger.info("Rootfs setup complete")
    
    async def start(self):
        """Start the container."""
        if self._state == ContainerState.RUNNING:
            logger.warning("Container already running")
            return
        
        logger.info("Starting container...")
        self._set_state(ContainerState.STARTING)
        
        try:
            # Mount proc, sys, dev if not already done
            await self._mount_filesystems()
            
            # Set hostname
            await self._set_hostname()
            
            self._set_state(ContainerState.RUNNING)
            logger.info("Container started successfully")
            
            # Start shell server for interactive access
            await self._start_shell_server()
            
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
            # Stop shell server
            await self._stop_shell_server()
            
            # Unmount filesystems
            await self._unmount_filesystems()
            
            self._set_state(ContainerState.STOPPED)
            logger.info("Container stopped")
            
        except Exception as e:
            logger.error(f"Failed to stop container: {e}")
            self._set_state(ContainerState.ERROR)
            raise
    
    async def restart(self):
        """Restart the container."""
        await self.stop()
        await asyncio.sleep(1)
        await self.start()
    
    async def _mount_filesystems(self):
        """Mount required filesystems for chroot."""
        # Mount proc
        proc_path = os.path.join(self._rootfs_path, "proc")
        if not self._is_mounted(proc_path):
            try:
                subprocess.run(["mount", "-t", "proc", "proc", proc_path], 
                             check=False, capture_output=True)
            except Exception as e:
                logger.warning(f"Could not mount proc: {e}")
        
        # Mount sys
        sys_path = os.path.join(self._rootfs_path, "sys")
        if not self._is_mounted(sys_path):
            try:
                subprocess.run(["mount", "-t", "sysfs", "sysfs", sys_path], 
                             check=False, capture_output=True)
            except Exception as e:
                logger.warning(f"Could not mount sys: {e}")
        
        # Mount dev
        dev_path = os.path.join(self._rootfs_path, "dev")
        if not self._is_mounted(dev_path):
            try:
                subprocess.run(["mount", "-t", "devpts", "devpts", dev_path], 
                             check=False, capture_output=True)
            except Exception as e:
                logger.warning(f"Could not mount dev: {e}")
    
    async def _unmount_filesystems(self):
        """Unmount filesystems."""
        for path in ["proc", "sys", "dev"]:
            full_path = os.path.join(self._rootfs_path, path)
            try:
                subprocess.run(["umount", full_path], check=False, capture_output=True)
            except:
                pass
    
    def _is_mounted(self, path: str) -> bool:
        """Check if path is mounted."""
        try:
            with open("/proc/mounts", "r") as f:
                for line in f:
                    if line.startswith(path + " "):
                        return True
        except:
            pass
        return False
    
    async def _set_hostname(self):
        """Set hostname inside container."""
        hostname_path = os.path.join(self._rootfs_path, "etc/hostname")
        try:
            with open(hostname_path, "w") as f:
                f.write("personal-cloud-os\n")
        except Exception as e:
            logger.warning(f"Could not set hostname: {e}")
    
    async def _start_shell_server(self):
        """Start Unix socket shell server for interactive access."""
        socket_path = os.path.expanduser("~/.local/run/pcos/container.sock")
        os.makedirs(os.path.dirname(socket_path), exist_ok=True)
        
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        
        # Create Unix socket server with threading for accept loop
        self._shell_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._shell_socket.bind(socket_path)
        os.chmod(socket_path, 0o600)
        self._shell_socket.listen(1)
        
        # Start accept loop in background thread
        self._shell_running = True
        import threading
        self._shell_accept_thread = threading.Thread(target=self._shell_accept_loop, daemon=True)
        self._shell_accept_thread.start()
        
        logger.info(f"Shell server listening on {socket_path}")
    
    def _shell_accept_loop(self):
        """Accept shell connections and spawn interactive shell."""
        import pty
        import select
        import os
        import subprocess
        
        while self._shell_running:
            try:
                self._shell_socket.settimeout(1.0)
                client, _ = self._shell_socket.accept()
                
                # Create pseudo-terminal
                master, slave = pty.openpty()
                
                # Set up environment
                env = os.environ.copy()
                rootfs_bin = os.path.join(self._rootfs_path, "bin")
                rootfs_sbin = os.path.join(self._rootfs_path, "sbin")
                rootfs_usr_bin = os.path.join(self._rootfs_path, "usr", "bin")
                rootfs_usr_sbin = os.path.join(self._rootfs_path, "usr", "sbin")
                env["PATH"] = f"{rootfs_bin}:{rootfs_sbin}:{rootfs_usr_bin}:{rootfs_usr_sbin}:/usr/local/bin:/usr/bin:/bin"
                env["HOME"] = self._home_path
                env["TERM"] = "xterm-256color"
                env["SHELL"] = "/bin/sh"
                
                # Spawn shell
                proc = subprocess.Popen(
                    ["/bin/sh"],
                    stdin=slave,
                    stdout=slave,
                    stderr=slave,
                    cwd=self._data_path,
                    env=env,
                    preexec_fn=os.setsid
                )
                
                # Relay data between socket and PTY
                while self._shell_running and proc.poll() is None:
                    r, _, _ = select.select([client, master], [], [], 0.1)
                    if client in r:
                        data = client.recv(1024)
                        if data:
                            os.write(master, data)
                    if master in r:
                        data = os.read(master, 1024)
                        if data:
                            client.send(data)
                
                proc.terminate()
                client.close()
                os.close(master)
                os.close(slave)
                
            except socket.timeout:
                continue
            except Exception as e:
                if self._shell_running:
                    logger.debug(f"Shell accept error: {e}")
                break
    
    async def _stop_shell_server(self):
        """Stop shell server."""
        self._shell_running = False
        
        if self._shell_socket:
            try:
                self._shell_socket.close()
            except:
                pass
            self._shell_socket = None
        
        socket_path = os.path.expanduser("~/.local/run/pcos/container.sock")
        if os.path.exists(socket_path):
            try:
                os.unlink(socket_path)
            except:
                pass
    
    async def execute(self, command: List[str], timeout: int = 30) -> Tuple[str, str, int]:
        """Execute a command in the container environment.
        
        Uses PATH to include rootfs binaries - no chroot needed.
        This gives us the Alpine environment without root privileges.
        """
        if self._state != ContainerState.RUNNING:
            raise RuntimeError("Container not running")
        
        # Build command string
        cmd_str = " ".join(command) if len(command) > 1 else command[0]
        
        # Set up environment with rootfs paths
        env = os.environ.copy()
        rootfs_bin = os.path.join(self._rootfs_path, "bin")
        rootfs_sbin = os.path.join(self._rootfs_path, "sbin")
        rootfs_usr_bin = os.path.join(self._rootfs_path, "usr", "bin")
        rootfs_usr_sbin = os.path.join(self._rootfs_path, "usr", "sbin")
        
        # Prepend rootfs paths to PATH
        existing_path = env.get("PATH", "")
        env["PATH"] = f"{rootfs_bin}:{rootfs_sbin}:{rootfs_usr_bin}:{rootfs_usr_sbin}:{existing_path}"
        env["HOME"] = self._home_path
        env["TERM"] = "xterm"
        
        try:
            result = subprocess.run(
                ["/bin/sh", "-c", cmd_str],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._data_path,
                env=env
            )
            return result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired:
            return "", "Command timed out", 124
        except Exception as e:
            return "", str(e), 1
    
    async def get_shell(self):
        """Get shell command for interactive access."""
        # Return command that uses rootfs PATH
        return ["/bin/sh"]
    
    async def get_info(self) -> ContainerInfo:
        """Get container information."""
        return ContainerInfo(
            id=self._container_id,
            name="personal-cloud-os",
            rootfs_path=self._rootfs_path,
            data_path=self._data_path,
            home_path=self._home_path,
            state=self._state.value,
            version="3.20"
        )
    
    def _set_state(self, state: ContainerState):
        """Set container state."""
        with self._lock:
            self._state = state
        
        # Publish state change event
        if self.event_bus:
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
    def container_id(self) -> str:
        """Get container ID."""
        return self._container_id
    
    @property
    def data_path(self) -> str:
        """Get data directory path."""
        return self._data_path
    
    @property
    def rootfs_path(self) -> str:
        """Get rootfs directory path."""
        return self._rootfs_path
