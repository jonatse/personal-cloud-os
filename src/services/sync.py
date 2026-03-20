"""
Sync Engine - Transport-aware file synchronisation for Personal Cloud OS.

Transport selection (via TransportManager):
  FAST   link → WireGuard tunnel (rsync/SCP over tunnel IP at full NIC speed)
  MEDIUM link → SwarmManager (torrent-style multi-peer chunk exchange)
  SLOW   link → RNS.Resource  (RNS built-in bulk transfer, auto-chunking)
  OFFLINE     → queue for later

Control protocol (JSON over RNS.Packet via PeerLinkService):
  Type 1  REQUEST_FILELIST  {type:1, ts:<iso>}
  Type 2  FILELIST          {type:2, files:{<path>: {path,size,mtime,hash}}}
  Type 3  REQUEST_FILE      {type:3, path:<str>, transport:<tier>}
  Type 5  FILE_COMPLETE     {type:5, path:<str>}
  Type 6  DELETE_FILE       {type:6, path:<str>}

File data transport:
  SLOW  → RNS.Resource advertised on the link; receiver accepts via
           link.set_resource_callback / link.set_resource_strategy
  FAST  → TransportManager handles (WireGuard rsync out-of-band)
  MEDIUM→ SwarmManager handles (HAVE/REQUEST/CHUNK/DONE JSON messages)
"""
import asyncio
import hashlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

import RNS

logger = logging.getLogger(__name__)

# ── Control message type constants ───────────────────────────────────────────
MSG_REQUEST_FILELIST = 1
MSG_FILELIST         = 2
MSG_REQUEST_FILE     = 3
MSG_FILE_COMPLETE    = 5
MSG_DELETE_FILE      = 6

# ── Swarm message prefix (handled by SwarmManager, not SyncEngine) ───────────
_SWARM_TYPES = {"have", "request", "chunk", "done"}


class SyncState(Enum):
    IDLE     = "idle"
    SYNCING  = "syncing"
    ERROR    = "error"


@dataclass
class FileInfo:
    path:  str
    size:  int
    mtime: float
    hash:  str = ""

    def to_dict(self) -> dict:
        return {"path": self.path, "size": self.size,
                "mtime": self.mtime, "hash": self.hash}

    @classmethod
    def from_dict(cls, d: dict) -> "FileInfo":
        return cls(**d)


@dataclass
class SyncStatus:
    state:        str = "idle"
    files_synced: int = 0
    files_total:  int = 0
    last_sync:    Optional[datetime] = None
    errors:       List[str] = field(default_factory=list)


class SyncEngine:
    """
    Synchronises ~/Sync with all discovered peers.
    Delegates bulk data transfer to TransportManager.
    """

    def __init__(self, config, event_bus, reticulum_service,
                 peer_link_service=None, transport_manager=None):
        self.config              = config
        self.event_bus           = event_bus
        self.reticulum_service   = reticulum_service
        self.peer_link_service   = peer_link_service
        self.transport_manager   = transport_manager   # set after construction

        self._running       = False
        self._sync_task:    Optional[asyncio.Task] = None
        self._event_loop:   Optional[asyncio.AbstractEventLoop] = None
        self._status        = SyncStatus()
        self._lock          = threading.Lock()

        self._local_files:    Dict[str, FileInfo] = {}
        self._remote_files:   Dict[str, Dict[str, FileInfo]] = {}  # peer_id → files
        self._receiving_files: Dict[str, int] = {}   # path → chunk count

        self._sync_dir      = os.path.expanduser("~/Sync")
        self._sync_interval = config.get("sync.sync_interval", 60)

        os.makedirs(self._sync_dir, exist_ok=True)

        self.event_bus.subscribe("peer.discovered", self._on_peer_discovered)
        self.event_bus.subscribe("peer.lost",       self._on_peer_lost)

        logger.info("SyncEngine initialised")

    def set_transport_manager(self, tm):
        """Wire in the TransportManager (called from main.py after construction)."""
        self.transport_manager = tm

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self):
        if self._running:
            return
        logger.info("Starting sync engine…")
        self._running     = True
        self._event_loop  = asyncio.get_event_loop()

        await self._scan_local_files()
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("Sync engine started")

    async def stop(self):
        logger.info("Stopping sync engine…")
        self._running = False
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        logger.info("Sync engine stopped")

    # ------------------------------------------------------------------ #
    # Event handlers                                                       #
    # ------------------------------------------------------------------ #

    async def _on_peer_discovered(self, event):
        peer_id = event.data.get("id")
        if not peer_id or not self.peer_link_service:
            return
        # Register inbound data callback for this peer
        self.peer_link_service.register_data_callback(
            peer_id, self._handle_peer_data)
        # Initiate a link
        self.peer_link_service.connect_to_peer(peer_id)

    async def _on_peer_lost(self, event):
        peer_id = event.data.get("id")
        if peer_id:
            self._remote_files.pop(peer_id, None)

    # ------------------------------------------------------------------ #
    # Sync loop                                                            #
    # ------------------------------------------------------------------ #

    async def _sync_loop(self):
        # Short initial delay so links can be established before first sync
        await asyncio.sleep(8)
        while self._running:
            try:
                await self._scan_local_files()
                await self._sync_all()
                await asyncio.sleep(self._sync_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Sync loop error: {exc}", exc_info=True)
                self._status.errors.append(str(exc))
                await asyncio.sleep(self._sync_interval)

    async def _sync_all(self):
        if not self.reticulum_service.is_running():
            return
        if not self.peer_link_service:
            return

        peers = self.reticulum_service.get_peers()
        if not peers:
            logger.debug("No peers — skipping sync")
            return

        logger.info(f"Syncing with {len(peers)} peer(s)…")
        self._status.state = SyncState.SYNCING.value

        for peer in peers:
            await self._sync_with_peer(peer)

        self._status.state      = SyncState.IDLE.value
        self._status.last_sync  = datetime.now()

    async def _sync_with_peer(self, peer):
        """Ensure we're connected and send a file-list request."""
        if not self.peer_link_service.is_connected_to(peer.id):
            logger.debug(f"Connecting to {peer.name}…")
            if not self.peer_link_service.connect_to_peer(peer.id):
                logger.warning(f"Could not connect to {peer.name}")
                return
            # Poll for ACTIVE (up to 10 s)
            for _ in range(20):
                await asyncio.sleep(0.5)
                if self.peer_link_service.is_connected_to(peer.id):
                    break
            else:
                logger.warning(f"Link to {peer.name} did not become ACTIVE in time")
                return

        sent = self.peer_link_service.send_json_to_peer(peer.id, {
            "type": MSG_REQUEST_FILELIST,
            "ts":   datetime.now().isoformat(),
        })
        if sent:
            logger.info(f"Sent file list request to {peer.name}")
        else:
            logger.warning(f"Failed to send file list request to {peer.name}")

    # ------------------------------------------------------------------ #
    # Inbound data dispatcher (called from RNS thread via PeerLinkService) #
    # ------------------------------------------------------------------ #

    def _handle_peer_data(self, peer_id: str, data: bytes):
        """
        Entry point for all inbound peer data.
        Runs in an RNS background thread — must not await directly.
        Schedules async work via run_coroutine_threadsafe.
        """
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception as exc:
            logger.error(f"Bad JSON from {peer_id}: {exc}")
            return

        # Swarm messages are delegated directly (SwarmManager is thread-safe)
        if msg.get("t") in _SWARM_TYPES and self.transport_manager:
            self.transport_manager.swarm.handle_message(peer_id, msg)
            return

        msg_type = msg.get("type")

        if msg_type == MSG_REQUEST_FILELIST:
            self._send_filelist(peer_id)

        elif msg_type == MSG_FILELIST:
            self._on_filelist_received(peer_id, msg)

        elif msg_type == MSG_REQUEST_FILE:
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    self._send_file(peer_id, msg.get("path", "")),
                    self._event_loop)

        elif msg_type == MSG_FILE_COMPLETE:
            logger.info(f"File transfer complete: {msg.get('path')} from {peer_id[:12]}")
            # Re-scan so the new file appears in status
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    self._scan_local_files(), self._event_loop)

        else:
            logger.debug(f"Unknown message type {msg_type} from {peer_id[:12]}")

    def _send_filelist(self, peer_id: str):
        """Send our file list to a peer (called from RNS thread — sync-safe)."""
        filelist = {p: fi.to_dict() for p, fi in self._local_files.items()}
        self.peer_link_service.send_json_to_peer(peer_id, {
            "type":  MSG_FILELIST,
            "files": filelist,
        })
        logger.info(f"Sent file list to {peer_id[:12]} ({len(filelist)} files)")

    def _on_filelist_received(self, peer_id: str, msg: dict):
        """Process received file list and request missing/newer files."""
        files_data = msg.get("files", {})
        remote = {p: FileInfo.from_dict(d) for p, d in files_data.items()}
        self._remote_files[peer_id] = remote
        logger.info(f"Received file list from {peer_id[:12]}: {len(remote)} files")

        if self._event_loop:
            asyncio.run_coroutine_threadsafe(
                self._request_needed_files(peer_id, remote),
                self._event_loop)

    # ------------------------------------------------------------------ #
    # File transfer                                                        #
    # ------------------------------------------------------------------ #

    async def _request_needed_files(self, peer_id: str,
                                    remote: Dict[str, FileInfo]):
        """Compare remote file list with local and request what we need."""
        needed = []
        for path, remote_fi in remote.items():
            local_fi = self._local_files.get(path)
            if local_fi is None:
                needed.append(path)
            elif remote_fi.hash and local_fi.hash and remote_fi.hash != local_fi.hash:
                if remote_fi.mtime > local_fi.mtime:
                    needed.append(path)
            elif remote_fi.mtime > (local_fi.mtime if local_fi else 0):
                needed.append(path)

        logger.info(f"Need {len(needed)} file(s) from {peer_id[:12]}")

        # Determine transport tier for this peer
        transport_tier = "rns"
        if self.transport_manager:
            from transport.detector import Transport
            t = self.transport_manager.get_transport_for_peer(peer_id)
            transport_tier = t.value

        for path in needed:
            self.peer_link_service.send_json_to_peer(peer_id, {
                "type":      MSG_REQUEST_FILE,
                "path":      path,
                "transport": transport_tier,
            })
            await asyncio.sleep(0.05)

    async def _send_file(self, peer_id: str, filepath: str):
        """Send a file to a peer using the appropriate transport."""
        if not filepath:
            return

        full_path = os.path.join(self._sync_dir, filepath)
        if not os.path.exists(full_path):
            logger.warning(f"Requested file not found: {filepath}")
            return

        file_size = os.path.getsize(full_path)

        # Determine transport
        transport_tier = "rns"
        if self.transport_manager:
            from transport.detector import Transport, LinkTier
            profile = self.peer_link_service.get_link_profile(peer_id)
            if profile:
                transport_tier = profile.transport.value

                # Check bandwidth budget, warn if needed
                ok, warn = self.transport_manager.governor.check_transfer(
                    profile, file_size)
                if not ok:
                    logger.warning(f"Transfer blocked: {warn}")
                    return
                if warn:
                    logger.warning(warn)

                if profile.tier == LinkTier.FAST:
                    # WireGuard handles the actual transfer
                    self.transport_manager.send_file(peer_id, full_path)
                    return

                if profile.tier == LinkTier.MEDIUM:
                    # Swarm handles it
                    self.transport_manager.send_file(peer_id, full_path)
                    return

        # SLOW / fallback: use RNS.Resource
        await self._send_file_rns_resource(peer_id, filepath, full_path)

    async def _send_file_rns_resource(self, peer_id: str,
                                      rel_path: str, full_path: str):
        """
        Send a file via RNS.Resource — the RNS built-in bulk transfer mechanism.
        Handles its own chunking, windowing, and retransmission.
        """
        try:
            link = self.peer_link_service._links.get(peer_id)
            if not link or link.status != RNS.Link.ACTIVE:
                logger.warning(f"RNS.Resource: link to {peer_id[:12]} not ACTIVE")
                return

            file_size = os.path.getsize(full_path)
            logger.info(f"RNS.Resource: sending {rel_path} "
                        f"({file_size/1024:.1f} KB) to {peer_id[:12]}")

            def _on_resource_concluded(resource):
                if resource.status == RNS.Resource.COMPLETE:
                    logger.info(f"RNS.Resource: {rel_path} delivered to {peer_id[:12]}")
                    self.peer_link_service.send_json_to_peer(peer_id, {
                        "type": MSG_FILE_COMPLETE,
                        "path": rel_path,
                    })
                else:
                    logger.error(f"RNS.Resource: {rel_path} failed "
                                 f"(status={resource.status})")

            with open(full_path, "rb") as f:
                data = f.read()

            # Metadata so the receiver knows which path to write
            metadata = json.dumps({"path": rel_path}).encode()

            resource = RNS.Resource(
                data=data,
                link=link,
                metadata=metadata,
                callback=_on_resource_concluded,
                auto_compress=True,
            )

            logger.info(f"RNS.Resource advertised: {rel_path} "
                        f"({resource.get_transfer_size()/1024:.1f} KB on wire)")

        except Exception as exc:
            logger.error(f"RNS.Resource send failed for {rel_path}: {exc}",
                         exc_info=True)

    # ------------------------------------------------------------------ #
    # Inbound RNS.Resource handling (registered per-link)                 #
    # ------------------------------------------------------------------ #

    def setup_resource_receiver(self, peer_id: str):
        """
        Register RNS.Resource callbacks on a newly ACTIVE link so we can
        receive files sent via _send_file_rns_resource.
        Called by main.py or PeerLinkService after link establishment.
        """
        link = self.peer_link_service._links.get(peer_id) if self.peer_link_service else None
        if not link:
            return

        link.set_resource_strategy(RNS.Link.ACCEPT_APP)
        link.set_resource_callback(
            lambda resource, pid=peer_id: self._on_resource_incoming(pid, resource))
        link.set_resource_concluded_callback(
            lambda resource, pid=peer_id: self._on_resource_concluded(pid, resource))

    def _on_resource_incoming(self, peer_id: str, resource) -> bool:
        """Return True to accept the incoming resource."""
        logger.info(f"RNS.Resource incoming from {peer_id[:12]}: "
                    f"{resource.get_transfer_size()/1024:.1f} KB")
        return True

    def _on_resource_concluded(self, peer_id: str, resource):
        """Write the received file to ~/Sync."""
        if resource.status != RNS.Resource.COMPLETE:
            logger.error(f"Incoming resource from {peer_id[:12]} failed "
                         f"(status={resource.status})")
            return
        try:
            metadata = json.loads(resource.metadata.decode()) if resource.metadata else {}
            rel_path = metadata.get("path", "received_file")
        except Exception:
            rel_path = "received_file"

        full_path  = os.path.join(self._sync_dir, rel_path)
        parent_dir = os.path.dirname(full_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        try:
            data = resource.data.read() if hasattr(resource.data, "read") else resource.data
            with open(full_path, "wb") as f:
                f.write(data)
            logger.info(f"RNS.Resource: received and wrote {rel_path} "
                        f"({len(data)/1024:.1f} KB)")
            # Trigger a local rescan
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    self._scan_local_files(), self._event_loop)
        except Exception as exc:
            logger.error(f"Failed to write received resource {rel_path}: {exc}",
                         exc_info=True)

    # ------------------------------------------------------------------ #
    # File scanning                                                        #
    # ------------------------------------------------------------------ #

    async def _scan_local_files(self):
        logger.debug("Scanning local files…")
        new_files: Dict[str, FileInfo] = {}

        for root, dirs, files in os.walk(self._sync_dir):
            for filename in files:
                fp  = os.path.join(root, filename)
                rel = os.path.relpath(fp, self._sync_dir)
                try:
                    st = os.stat(fp)
                    new_files[rel] = FileInfo(
                        path=rel,
                        size=st.st_size,
                        mtime=st.st_mtime,
                        hash=await self._hash_file(fp),
                    )
                except Exception as exc:
                    logger.warning(f"Error scanning {fp}: {exc}")

        self._local_files = new_files
        logger.info(f"Found {len(self._local_files)} local file(s)")

    async def _hash_file(self, path: str) -> str:
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    def get_status(self) -> SyncStatus:
        self._status.files_total = len(self._local_files)
        return self._status

    def is_running(self) -> bool:
        return self._running

    @property
    def sync_dir(self) -> str:
        return self._sync_dir
