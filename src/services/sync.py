"""Sync Engine - Syncs files with discovered peers via Reticulum links."""
import asyncio
import logging
import hashlib
import os
import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import threading


logger = logging.getLogger(__name__)


class ConflictResolution(Enum):
    """Conflict resolution strategies."""
    NEWEST = "newest"
    OLDEST = "oldest"
    MANUAL = "manual"
    SKIP = "skip"


class SyncDirection(Enum):
    """Sync direction."""
    UPLOAD = "upload"
    DOWNLOAD = "download"
    BIDIRECTIONAL = "bidirectional"


# Sync protocol message types
SYNC_MSG_REQUEST_FILELIST = 1
SYNC_MSG_FILELIST = 2
SYNC_MSG_REQUEST_FILE = 3
SYNC_MSG_FILE_DATA = 4
SYNC_MSG_FILE_COMPLETE = 5
SYNC_MSG_DELETE_FILE = 6


@dataclass
class FileInfo:
    """Information about a file."""
    path: str
    size: int
    mtime: float
    hash: str = ""
    
    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "size": self.size,
            "mtime": self.mtime,
            "hash": self.hash
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'FileInfo':
        return cls(**data)


@dataclass
class SyncConflict:
    """Represents a sync conflict."""
    file_path: str
    local_info: FileInfo
    remote_info: FileInfo
    peer_id: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SyncStatus:
    """Current sync status."""
    state: str = "idle"  # idle, syncing, error
    files_synced: int = 0
    files_total: int = 0
    bytes_synced: int = 0
    bytes_total: int = 0
    current_file: str = ""
    last_sync: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)


class SyncEngine:
    """
    Background service for syncing files with discovered peers.
    
    Uses Reticulum links for encrypted peer-to-peer file transfer.
    """
    
    def __init__(self, config, event_bus, reticulum_service, peer_link_service=None):
        """Initialize sync engine."""
        self.config = config
        self.event_bus = event_bus
        self.reticulum_service = reticulum_service
        self.peer_link_service = peer_link_service
        
        self._running = False
        self._sync_task: Optional[asyncio.Task] = None
        self._event_loop = None
        self._status = SyncStatus()
        self._lock = threading.Lock()
        
        # File tracking
        self._local_files: Dict[str, FileInfo] = {}
        self._remote_files: Dict[str, Dict[str, FileInfo]] = {}  # peer_id -> {path -> FileInfo}
        self._receiving_files: Dict[str, int] = {}               # path -> chunk count
        self._sync_dir = os.path.expanduser("~/Sync")
        
        # Sync settings
        self._sync_interval = config.get("sync.sync_interval", 60)
        self._conflict_resolution = ConflictResolution(
            config.get("sync.conflict_resolution", "newest")
        )
        
        # Ensure sync directory exists
        os.makedirs(self._sync_dir, exist_ok=True)
        
        # Register for peer events
        self.event_bus.subscribe("peer.discovered", self._on_peer_discovered)
        self.event_bus.subscribe("peer.lost", self._on_peer_lost)
        
        logger.info("SyncEngine initialized")
    
    def set_peer_link_service(self, peer_link_service):
        """Set the peer link service."""
        self.peer_link_service = peer_link_service
    
    async def _on_peer_discovered(self, event):
        """Handle new peer discovered."""
        peer_id = event.data.get("id")
        if peer_id and self.peer_link_service:
            # Register data callback for this peer
            self.peer_link_service.register_data_callback(
                peer_id, 
                self._handle_peer_data
            )
            # Connect to peer
            self.peer_link_service.connect_to_peer(peer_id)
    
    async def _on_peer_lost(self, event):
        """Handle peer lost."""
        peer_id = event.data.get("id")
        if peer_id and peer_id in self._remote_files:
            del self._remote_files[peer_id]
    
    async def start(self):
        """Start the sync engine."""
        if self._running:
            logger.warning("Sync engine already running")
            return
        
        logger.info("Starting sync engine...")
        self._running = True
        
        # Scan local files
        self._event_loop = asyncio.get_event_loop()
        await self._scan_local_files()
        
        # Start periodic sync
        self._sync_task = asyncio.create_task(self._sync_loop())
        
        logger.info("Sync engine started")
    
    async def stop(self):
        """Stop the sync engine."""
        logger.info("Stopping sync engine...")
        self._running = False
        
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Sync engine stopped")
    
    async def _sync_loop(self):
        """Periodic sync loop."""
        # Perform a first sync shortly after startup rather than waiting the full interval
        await asyncio.sleep(5)
        while self._running:
            try:
                await self._scan_local_files()
                await self.sync_all()
                await asyncio.sleep(self._sync_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Sync loop error: {e}")
                self._status.errors.append(str(e))
                await asyncio.sleep(self._sync_interval)
    
    async def _scan_local_files(self):
        """Scan local sync directory."""
        logger.info("Scanning local files...")
        self._local_files.clear()
        
        for root, dirs, files in os.walk(self._sync_dir):
            for filename in files:
                filepath = os.path.join(root, filename)
                rel_path = os.path.relpath(filepath, self._sync_dir)
                
                try:
                    stat = os.stat(filepath)
                    file_info = FileInfo(
                        path=rel_path,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                        hash=await self._hash_file(filepath)
                    )
                    self._local_files[rel_path] = file_info
                except Exception as e:
                    logger.warning(f"Error scanning {filepath}: {e}")
        
        logger.info(f"Found {len(self._local_files)} local files")
    
    async def _hash_file(self, filepath: str) -> str:
        """Calculate file hash."""
        hasher = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            logger.warning(f"Error hashing {filepath}: {e}")
            return ""
    
    async def sync_all(self):
        """Sync with all discovered peers."""
        if not self.reticulum_service.is_running():
            logger.debug("Reticulum not running, skipping sync")
            return
        
        if not self.peer_link_service:
            logger.warning("Peer link service not available, skipping sync")
            return
        
        peers = self.reticulum_service.get_peers()
        if not peers:
            logger.debug("No peers discovered, skipping sync")
            return
        
        logger.info(f"Syncing with {len(peers)} peers...")
        
        self._status.state = "syncing"
        self._status.files_synced = 0
        self._status.files_total = len(self._local_files) * len(peers)
        
        await self.event_bus.publish(type="sync.started", data=self._status.__dict__, source="sync")
        
        try:
            for peer in peers:
                await self._sync_with_peer(peer)
            
            self._status.state = "idle"
            self._status.last_sync = datetime.now()
            
            await self.event_bus.publish(type="sync.completed", data=self._status.__dict__, source="sync")
        except Exception as e:
            self._status.state = "error"
            self._status.errors.append(str(e))
            logger.error(f"Sync error: {e}")
            
            await self.event_bus.publish(type="sync.failed", data={"error": str(e)}, source="sync")
    
    async def _sync_with_peer(self, peer):
        """Sync files with a specific peer."""
        logger.info(f"Syncing with peer: {peer.name}")
        
        # Ensure we're connected
        if not self.peer_link_service.is_connected_to(peer.id):
            logger.debug(f"Not connected to {peer.name}, connecting...")
            connected = self.peer_link_service.connect_to_peer(peer.id)
            if not connected:
                logger.warning(f"Could not connect to peer: {peer.name}")
                return
            # Wait for connection
            await asyncio.sleep(1)
        
        # Request peer's file list
        try:
            # Send file list request
            request = {
                "type": SYNC_MSG_REQUEST_FILELIST,
                "timestamp": datetime.now().isoformat()
            }
            self.peer_link_service.send_json_to_peer(peer.id, request)
            
            # Wait for response (handled in _handle_peer_data)
            
        except Exception as e:
            logger.error(f"Error syncing with peer {peer.name}: {e}")
    
    def _handle_peer_data(self, peer_id: str, data: bytes):
        """Handle incoming data from a peer."""
        try:
            # Parse JSON message
            message = json.loads(data.decode('utf-8'))
            msg_type = message.get("type")
            
            if msg_type == SYNC_MSG_REQUEST_FILELIST:
                # Peer wants our file list
                self._send_filelist(peer_id)
                
            elif msg_type == SYNC_MSG_FILELIST:
                # Received peer's file list
                filelist_data = message.get("files", {})
                self._remote_files[peer_id] = {
                    path: FileInfo.from_dict(info) 
                    for path, info in filelist_data.items()
                }
                logger.info(f"Received file list from {peer_id}: {len(self._remote_files[peer_id])} files")
                # Start sync
                if self._event_loop:
                    asyncio.run_coroutine_threadsafe(self._perform_sync(peer_id), self._event_loop)
                
            elif msg_type == SYNC_MSG_REQUEST_FILE:
                # Peer wants a file
                if self._event_loop:
                    asyncio.run_coroutine_threadsafe(self._send_file(peer_id, message.get("path")), self._event_loop)
                
            elif msg_type == SYNC_MSG_FILE_DATA:
                # Received file data
                if self._event_loop:
                    asyncio.run_coroutine_threadsafe(self._receive_file_data(peer_id, message), self._event_loop)
                
            elif msg_type == SYNC_MSG_FILE_COMPLETE:
                # File transfer complete
                logger.info(f"File transfer complete: {message.get('path')}")
                
        except Exception as e:
            logger.error(f"Error handling peer data: {e}")
    
    def _send_filelist(self, peer_id: str):
        """Send our file list to a peer."""
        filelist = {path: info.to_dict() for path, info in self._local_files.items()}
        
        response = {
            "type": SYNC_MSG_FILELIST,
            "files": filelist
        }
        
        self.peer_link_service.send_json_to_peer(peer_id, response)
        logger.info(f"Sent file list to {peer_id}: {len(filelist)} files")
    
    async def _perform_sync(self, peer_id: str):
        """Perform sync with peer based on file lists."""
        if peer_id not in self._remote_files:
            return
        
        remote_files = self._remote_files[peer_id]
        
        # Find files we need from peer (not in local or different)
        files_to_get = []
        for path, remote_info in remote_files.items():
            if path not in self._local_files:
                files_to_get.append(path)
            else:
                local_info = self._local_files[path]
                # Compare by hash or mtime
                if remote_info.hash and local_info.hash:
                    if remote_info.hash != local_info.hash:
                        files_to_get.append(path)
                elif remote_info.mtime > local_info.mtime:
                    files_to_get.append(path)
        
        logger.info(f"Need to get {len(files_to_get)} files from {peer_id}")
        
        # Request files
        for path in files_to_get:
            request = {
                "type": SYNC_MSG_REQUEST_FILE,
                "path": path
            }
            self.peer_link_service.send_json_to_peer(peer_id, request)
            await asyncio.sleep(0.1)  # Small delay between requests
    
    async def _send_file(self, peer_id: str, filepath: str):
        """Send a file to a peer."""
        full_path = os.path.join(self._sync_dir, filepath)
        
        if not os.path.exists(full_path):
            logger.warning(f"File not found: {filepath}")
            return
        
        try:
            # Read and send file in chunks
            chunk_size = 8192
            with open(full_path, 'rb') as f:
                chunk_num = 0
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    
                    message = {
                        "type": SYNC_MSG_FILE_DATA,
                        "path": filepath,
                        "chunk": chunk_num,
                        "data": chunk.hex()  # Send as hex
                    }
                    self.peer_link_service.send_json_to_peer(peer_id, message)
                    chunk_num += 1
                    await asyncio.sleep(0.01)  # Rate limiting
            
            # Send completion
            complete = {
                "type": SYNC_MSG_FILE_COMPLETE,
                "path": filepath
            }
            self.peer_link_service.send_json_to_peer(peer_id, complete)
            
            logger.info(f"Sent file to {peer_id}: {filepath}")
            
        except Exception as e:
            logger.error(f"Error sending file {filepath}: {e}")
    
    async def _receive_file_data(self, peer_id: str, message: dict):
        """Receive file data from a peer."""
        filepath = message.get("path")
        chunk_num = message.get("chunk", 0)
        data_hex = message.get("data", "")

        if not filepath:
            return

        full_path = os.path.join(self._sync_dir, filepath)

        # Ensure parent directory exists (guard against empty dirname for root-level files)
        parent_dir = os.path.dirname(full_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        try:
            chunk_data = bytes.fromhex(data_hex)

            # Truncate on first chunk, append on subsequent chunks
            mode = 'wb' if chunk_num == 0 else 'ab'
            with open(full_path, mode) as f:
                f.write(chunk_data)

            # Track received chunk count; safe for any chunk_num
            self._receiving_files.setdefault(filepath, 0)
            self._receiving_files[filepath] += 1

        except Exception as e:
            logger.error(f"Error receiving file {filepath}: {e}")
    
    async def add_file(self, filepath: str):
        """Add a file to sync."""
        rel_path = os.path.relpath(filepath, self._sync_dir)
        
        try:
            stat = os.stat(filepath)
            file_info = FileInfo(
                path=rel_path,
                size=stat.st_size,
                mtime=stat.st_mtime,
                hash=await self._hash_file(filepath)
            )
            self._local_files[rel_path] = file_info
            logger.info(f"Added file to sync: {rel_path}")
        except Exception as e:
            logger.error(f"Error adding file: {e}")
    
    async def remove_file(self, filepath: str):
        """Remove a file from sync."""
        rel_path = os.path.relpath(filepath, self._sync_dir)
        if rel_path in self._local_files:
            del self._local_files[rel_path]
            logger.info(f"Removed file from sync: {rel_path}")
    
    def get_local_files(self) -> Dict[str, FileInfo]:
        """Get all local files being tracked."""
        return self._local_files.copy()
    
    def get_remote_files(self, peer_id: str) -> Dict[str, FileInfo]:
        """Get all remote files from a peer."""
        return self._remote_files.get(peer_id, {}).copy()
    
    def get_status(self) -> SyncStatus:
        """Get current sync status."""
        # Always reflect the live local file count so the CLI shows real numbers
        self._status.files_total = len(self._local_files)
        return self._status
    
    def is_running(self) -> bool:
        """Check if sync engine is running."""
        return self._running
    
    @property
    def sync_dir(self) -> str:
        """Get sync directory path."""
        return self._sync_dir
