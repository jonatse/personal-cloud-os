"""
Sync Engine v2 - RNS.Resource-based file synchronisation

Protocol (all control messages are JSON over RNS.Packet via PeerLinkService):

  On link established → both sides immediately send INDEX_OFFER
  INDEX_OFFER  {type:10, device_id, index_id, files: {path: FileRecord}}
  NEED_LIST    {type:11, files: [path, ...]}          ← "please send these"
  FILE_DONE    {type:12, path, hash}                  ← "I wrote this file ok"

File data: one RNS.Resource per file, metadata = JSON {path, hash, version}
  - RNS.Resource handles chunking, windowing, retransmission internally
  - Resource transfers keep the link alive naturally (traffic resets stale timer)
  - Receiver writes to ~/Sync/<path> on completion, then sends FILE_DONE

Vector clocks (conflict detection):
  Each FileRecord carries version = {device_id: int, ...}
  If neither clock dominates → conflict → keep both with .conflict-<devid> suffix

Index ID:
  A per-device random 64-bit hex string. Changes only if the index is wiped.
  Persisted to ~/.local/share/pcos/index_id. On reconnect, if the remote's
  index_id matches what we last saw AND they send a max_sequence, we could
  do delta sync. For v2 we always send the full index (simple, correct).

Link lifecycle:
  Links stay open for as long as transfers are in flight. RNS.Resource keeps
  the link alive. After all transfers complete, the link may close naturally
  (STALE_TIME=720s) or be re-used on the next sync cycle.
"""
import asyncio
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import RNS

logger = logging.getLogger(__name__)

# ── Wire protocol constants ────────────────────────────────────────────────────
MSG_INDEX_OFFER = 10   # {type, device_id, index_id, files: {path: FileRecord}}
MSG_NEED_LIST   = 11   # {type, files: [path, ...]}
MSG_FILE_DONE   = 12   # {type, path, hash}


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class FileRecord:
    """Represents one file in the sync index."""
    path:    str
    size:    int
    mtime:   float
    hash:    str                          # SHA-256 hex
    version: Dict[str, int] = field(default_factory=dict)  # {device_id: counter}

    def to_dict(self) -> dict:
        return {
            "path":    self.path,
            "size":    self.size,
            "mtime":   self.mtime,
            "hash":    self.hash,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FileRecord":
        return cls(
            path    = d["path"],
            size    = d["size"],
            mtime   = d["mtime"],
            hash    = d.get("hash", ""),
            version = d.get("version", {}),
        )

    def dominates(self, other: "FileRecord") -> bool:
        """Return True if self's vector clock >= other's on all devices."""
        all_keys = set(self.version) | set(other.version)
        return all(self.version.get(k, 0) >= other.version.get(k, 0) for k in all_keys)

    def conflicts_with(self, other: "FileRecord") -> bool:
        """Return True if neither clock dominates the other."""
        return not self.dominates(other) and not other.dominates(self)


@dataclass
class SyncStatus:
    state:         str = "idle"
    files_local:   int = 0
    files_synced:  int = 0
    active_transfers: int = 0
    last_sync:     Optional[datetime] = None
    errors:        List[str] = field(default_factory=list)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _sha256(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _load_index_id(store_dir: str) -> str:
    """Load or create a persistent random index ID for this device."""
    path = os.path.join(store_dir, "index_id")
    try:
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip()
    except Exception:
        pass
    index_id = uuid.uuid4().hex
    os.makedirs(store_dir, exist_ok=True)
    with open(path, "w") as f:
        f.write(index_id)
    return index_id


# ── Main engine ────────────────────────────────────────────────────────────────

class SyncEngine:
    """
    Synchronises ~/Sync with all discovered peers using RNS.Resource.

    On every link establishment, both sides immediately exchange their full
    index (INDEX_OFFER). Each side computes what it needs (NEED_LIST) and
    begins sending files via RNS.Resource — one Resource per file. The remote
    accepts, writes to disk, and sends FILE_DONE. No polling required.
    """

    def __init__(self, config, event_bus, reticulum_service,
                 peer_link_service=None, transport_manager=None):
        self.config            = config
        self.event_bus         = event_bus
        self.reticulum_service = reticulum_service
        self.peer_link_service = peer_link_service
        self.transport_manager = transport_manager

        self._running     = False
        self._sync_task:  Optional[asyncio.Task] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._status      = SyncStatus()
        self._lock        = threading.Lock()

        # Local file index: path → FileRecord
        self._local_files: Dict[str, FileRecord] = {}

        # Remote indexes: peer_id → {path → FileRecord}
        self._remote_files: Dict[str, Dict[str, FileRecord]] = {}

        # In-flight outbound Resources: peer_id → {path → RNS.Resource}
        self._outbound: Dict[str, Dict[str, object]] = {}

        # Device identity
        self._device_id = config.get("device.id", "unknown")
        store_dir       = os.path.expanduser("~/.local/share/pcos")
        self._index_id  = _load_index_id(store_dir)

        self._sync_dir      = os.path.expanduser("~/Sync")
        self._sync_interval = config.get("sync.sync_interval", 60)
        os.makedirs(self._sync_dir, exist_ok=True)

        # Subscribe to events
        self.event_bus.subscribe("peer.discovered", self._on_peer_discovered)
        self.event_bus.subscribe("peer.lost",       self._on_peer_lost)

        logger.info("SyncEngine v2 initialised (RNS.Resource transport)")

    def set_transport_manager(self, tm):
        self.transport_manager = tm

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self):
        if self._running:
            return
        logger.info("Starting sync engine…")
        self._running    = True
        self._event_loop = asyncio.get_event_loop()

        # Re-register data callback whenever a link comes up
        if self.peer_link_service:
            self.peer_link_service.register_link_callback(self._on_link_state_changed)

        await self._scan_local_files()
        self._sync_task = asyncio.create_task(self._periodic_scan_loop())
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

    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> SyncStatus:
        self._status.files_local = len(self._local_files)
        with self._lock:
            self._status.active_transfers = sum(
                len(v) for v in self._outbound.values())
        return self._status

    @property
    def sync_dir(self) -> str:
        return self._sync_dir

    # ── Event handlers ─────────────────────────────────────────────────

    async def _on_peer_discovered(self, event):
        peer_id = event.data.get("id")
        if not peer_id or not self.peer_link_service:
            return
        self.peer_link_service.register_data_callback(
            peer_id, self._handle_peer_data)
        self.peer_link_service.connect_to_peer(peer_id)

    async def _on_peer_lost(self, event):
        peer_id = event.data.get("id")
        if peer_id:
            self._remote_files.pop(peer_id, None)

    def _on_link_state_changed(self, peer_id: str, state):
        """Called by PeerLinkService when a link becomes CONNECTED."""
        from services.peer_link import LinkState
        if state == LinkState.CONNECTED:
            logger.debug(f"Link up to {peer_id[:12]} — registering callbacks and sending index")
            self.peer_link_service.register_data_callback(
                peer_id, self._handle_peer_data)
            # Set up RNS.Resource receiver on this link
            self._setup_resource_receiver(peer_id)
            # Send our index immediately
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    self._send_index_offer(peer_id), self._event_loop)
        elif state == LinkState.DISCONNECTED:
            # Clean up in-flight transfers for this peer
            with self._lock:
                self._outbound.pop(peer_id, None)

    # ── Periodic scan ──────────────────────────────────────────────────

    async def _periodic_scan_loop(self):
        """Rescan local files periodically and re-offer index to all peers."""
        await asyncio.sleep(10)
        while self._running:
            try:
                prev_hashes = {p: r.hash for p, r in self._local_files.items()}
                await self._scan_local_files()

                # If any file changed, re-offer index to all connected peers
                new_hashes = {p: r.hash for p, r in self._local_files.items()}
                if new_hashes != prev_hashes:
                    logger.info("Local files changed — re-offering index to peers")
                    peers = self.peer_link_service.get_connected_peers() \
                        if self.peer_link_service else []
                    for peer_id in peers:
                        await self._send_index_offer(peer_id)

                await asyncio.sleep(self._sync_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Scan loop error: {exc}", exc_info=True)
                await asyncio.sleep(self._sync_interval)

    # ── Index exchange ─────────────────────────────────────────────────

    async def _send_index_offer(self, peer_id: str):
        """Send our full index to a peer."""
        if not self.peer_link_service:
            return
        if not self.peer_link_service.is_connected_to(peer_id):
            return

        files_dict = {p: r.to_dict() for p, r in self._local_files.items()}
        msg = {
            "type":      MSG_INDEX_OFFER,
            "device_id": self._device_id,
            "index_id":  self._index_id,
            "files":     files_dict,
        }
        sent = self.peer_link_service.send_json_to_peer(peer_id, msg)
        if sent:
            logger.info(f"Sent index offer to {peer_id[:12]} ({len(files_dict)} files)")
        else:
            logger.warning(f"Failed to send index offer to {peer_id[:12]}")

    def _on_index_offer(self, peer_id: str, msg: dict):
        """Process an incoming index offer and request what we need."""
        files_data  = msg.get("files", {})
        remote_files = {p: FileRecord.from_dict(d) for p, d in files_data.items()}
        self._remote_files[peer_id] = remote_files
        logger.info(
            f"Received index from {peer_id[:12]}: {len(remote_files)} file(s)")

        # Compute what we need
        needed = self._compute_needed(remote_files)
        if not needed:
            logger.info(f"Already up to date with {peer_id[:12]}")
            return

        logger.info(f"Need {len(needed)} file(s) from {peer_id[:12]}")
        msg_out = {"type": MSG_NEED_LIST, "files": needed}
        self.peer_link_service.send_json_to_peer(peer_id, msg_out)

    def _compute_needed(self, remote: Dict[str, FileRecord]) -> List[str]:
        """
        Return list of paths we should request from the remote.
        Uses vector clocks where available, falls back to mtime.
        """
        needed = []
        for path, remote_rec in remote.items():
            local_rec = self._local_files.get(path)

            if local_rec is None:
                # We don't have it at all
                needed.append(path)
                continue

            if remote_rec.hash == local_rec.hash:
                # Identical content — nothing to do
                continue

            if remote_rec.version and local_rec.version:
                # Use vector clock
                if remote_rec.dominates(local_rec):
                    needed.append(path)
                elif remote_rec.conflicts_with(local_rec):
                    # Both changed independently — we'll keep both
                    logger.warning(
                        f"Conflict detected for {path} — will keep both versions")
                    needed.append(path)
                # else: local dominates → remote is old, skip
            else:
                # No vector clocks: fall back to mtime
                if remote_rec.mtime > local_rec.mtime:
                    needed.append(path)

        return needed

    def _on_need_list(self, peer_id: str, msg: dict):
        """Peer told us what it needs — send each file via RNS.Resource."""
        paths = msg.get("files", [])
        logger.info(f"Peer {peer_id[:12]} needs {len(paths)} file(s)")
        for path in paths:
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    self._send_file_resource(peer_id, path),
                    self._event_loop)

    # ── File sending via RNS.Resource ──────────────────────────────────

    async def _send_file_resource(self, peer_id: str, rel_path: str):
        """Send a file to a peer via RNS.Resource."""
        full_path = os.path.join(self._sync_dir, rel_path)
        if not os.path.exists(full_path):
            logger.warning(f"Requested file not found: {rel_path}")
            return

        link = self.peer_link_service._links.get(peer_id)
        if not link or link.status != RNS.Link.ACTIVE:
            logger.warning(f"No active link to {peer_id[:12]} for file send")
            return

        # Check if already sending this file to this peer
        with self._lock:
            if peer_id in self._outbound and rel_path in self._outbound[peer_id]:
                logger.debug(f"Already sending {rel_path} to {peer_id[:12]}, skipping")
                return
            self._outbound.setdefault(peer_id, {})[rel_path] = None  # placeholder

        file_size = os.path.getsize(full_path)
        file_hash = _sha256(full_path)
        local_rec = self._local_files.get(rel_path)
        version   = local_rec.version if local_rec else {}

        logger.info(
            f"Sending {rel_path} ({file_size/1024:.1f} KB) → {peer_id[:12]} via RNS.Resource")

        try:
            with open(full_path, "rb") as f:
                data = f.read()

            metadata = json.dumps({
                "path":    rel_path,
                "hash":    file_hash,
                "version": version,
            }).encode()

            def _on_concluded(resource, pid=peer_id, path=rel_path):
                with self._lock:
                    self._outbound.get(pid, {}).pop(path, None)
                if resource.status == RNS.Resource.COMPLETE:
                    logger.info(f"Delivered {path} → {pid[:12]}")
                else:
                    logger.error(
                        f"Resource failed for {path} → {pid[:12]} "
                        f"(status={resource.status})")

            resource = RNS.Resource(
                data=data,
                link=link,
                metadata=metadata,
                callback=_on_concluded,
                auto_compress=True,
            )

            with self._lock:
                self._outbound.setdefault(peer_id, {})[rel_path] = resource

            self._status.active_transfers += 1
            logger.debug(
                f"RNS.Resource advertised: {rel_path} "
                f"({resource.get_transfer_size()/1024:.1f} KB on wire)")

        except Exception as exc:
            with self._lock:
                self._outbound.get(peer_id, {}).pop(rel_path, None)
            logger.error(f"Resource send error {rel_path}: {exc}", exc_info=True)

    # ── Resource receiving ─────────────────────────────────────────────

    def _setup_resource_receiver(self, peer_id: str):
        """Register RNS.Resource callbacks on a newly active link."""
        link = self.peer_link_service._links.get(peer_id) \
            if self.peer_link_service else None
        if not link:
            return
        link.set_resource_strategy(RNS.Link.ACCEPT_APP)
        link.set_resource_callback(
            lambda res, pid=peer_id: self._on_resource_incoming(pid, res))
        link.set_resource_concluded_callback(
            lambda res, pid=peer_id: self._on_resource_concluded(pid, res))
        logger.debug(f"Resource receiver set up for {peer_id[:12]}")

    def _on_resource_incoming(self, peer_id: str, resource) -> bool:
        size_kb = resource.get_transfer_size() / 1024
        logger.info(
            f"Incoming resource from {peer_id[:12]}: {size_kb:.1f} KB — accepting")
        return True  # accept all

    def _on_resource_concluded(self, peer_id: str, resource):
        """Called when an inbound RNS.Resource finishes."""
        self._status.active_transfers = max(0, self._status.active_transfers - 1)

        if resource.status != RNS.Resource.COMPLETE:
            logger.error(
                f"Inbound resource from {peer_id[:12]} failed "
                f"(status={resource.status})")
            return

        # Parse metadata
        try:
            meta    = json.loads(resource.metadata.decode()) \
                if resource.metadata else {}
            rel_path = meta.get("path", "received_file")
            expected_hash = meta.get("hash", "")
            version  = meta.get("version", {})
        except Exception:
            rel_path      = "received_file"
            expected_hash = ""
            version       = {}

        full_path  = os.path.join(self._sync_dir, rel_path)
        parent_dir = os.path.dirname(full_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        # Read resource data
        try:
            data = resource.data.read() \
                if hasattr(resource.data, "read") else resource.data
        except Exception as exc:
            logger.error(f"Could not read resource data: {exc}")
            return

        # Verify hash
        actual_hash = hashlib.sha256(data).hexdigest()
        if expected_hash and actual_hash != expected_hash:
            logger.error(
                f"Hash mismatch for {rel_path}: "
                f"expected {expected_hash[:16]} got {actual_hash[:16]}")
            return

        # Conflict check: if local copy exists and clocks conflict, rename
        local_rec = self._local_files.get(rel_path)
        if local_rec and local_rec.version and version:
            incoming = FileRecord(
                path=rel_path, size=len(data),
                mtime=time.time(), hash=actual_hash, version=version)
            if incoming.conflicts_with(local_rec):
                # Rename existing to conflict copy
                dev_id    = peer_id[:8]
                base, ext = os.path.splitext(full_path)
                conflict_path = f"{base}.conflict-{dev_id}{ext}"
                try:
                    os.rename(full_path, conflict_path)
                    logger.warning(
                        f"Conflict for {rel_path}: existing saved as "
                        f"{os.path.basename(conflict_path)}")
                except Exception:
                    pass

        # Write the file
        try:
            with open(full_path, "wb") as f:
                f.write(data)
            logger.info(
                f"Received {rel_path} from {peer_id[:12]} "
                f"({len(data)/1024:.1f} KB) ✓")
        except Exception as exc:
            logger.error(f"Write error for {rel_path}: {exc}")
            return

        # Notify sender
        self.peer_link_service.send_json_to_peer(peer_id, {
            "type": MSG_FILE_DONE,
            "path": rel_path,
            "hash": actual_hash,
        })

        # Rescan so the new file shows up in the index
        if self._event_loop:
            asyncio.run_coroutine_threadsafe(
                self._scan_local_files(), self._event_loop)

    # ── Inbound control message dispatcher ────────────────────────────

    def _handle_peer_data(self, peer_id: str, data: bytes):
        """
        Entry point for all inbound control messages.
        Runs in an RNS background thread.
        """
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception as exc:
            logger.error(f"Bad JSON from {peer_id[:12]}: {exc}")
            return

        msg_type = msg.get("type")

        if msg_type == MSG_INDEX_OFFER:
            self._on_index_offer(peer_id, msg)

        elif msg_type == MSG_NEED_LIST:
            self._on_need_list(peer_id, msg)

        elif msg_type == MSG_FILE_DONE:
            path = msg.get("path", "?")
            logger.info(f"Peer {peer_id[:12]} confirmed receipt of {path}")
            self._status.files_synced += 1
            self._status.last_sync = datetime.now()

        else:
            logger.debug(f"Unknown msg type {msg_type} from {peer_id[:12]}")

    # ── Local file scanning ────────────────────────────────────────────

    async def _scan_local_files(self):
        logger.debug("Scanning local files…")
        new_files: Dict[str, FileRecord] = {}

        for root, dirs, files in os.walk(self._sync_dir):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for filename in files:
                if filename.startswith("."):
                    continue
                fp  = os.path.join(root, filename)
                rel = os.path.relpath(fp, self._sync_dir)
                try:
                    st        = os.stat(fp)
                    file_hash = _sha256(fp)

                    # Preserve existing vector clock if hash unchanged
                    existing = self._local_files.get(rel)
                    if existing and existing.hash == file_hash:
                        version = existing.version
                    else:
                        # File is new or changed: increment our device counter
                        old_version = existing.version if existing else {}
                        version = dict(old_version)
                        version[self._device_id] = \
                            version.get(self._device_id, 0) + 1

                    new_files[rel] = FileRecord(
                        path=rel, size=st.st_size,
                        mtime=st.st_mtime, hash=file_hash,
                        version=version,
                    )
                except Exception as exc:
                    logger.warning(f"Error scanning {fp}: {exc}")

        self._local_files = new_files
        self._status.files_local = len(new_files)
        logger.info(f"Found {len(new_files)} local file(s)")
