"""
Sync Engine v3 — RNS-native

Uses RNS built-in request/response for everything:

  link.request(PATH_INDEX) → gets peer's file index
  link.request(PATH_FILE, {"path": ...}) → gets file bytes

The remote side handles these via request handlers registered on their
destination (in ReticulumPeerService). RNS automatically uses
RNS.Resource for large responses (files), with built-in chunking,
windowing, flow control, and retransmission.

No PeerLinkService. No custom packet protocol. No set_packet_callback.
No set_resource_strategy. No inbound link hacks.

Vector clocks track file versions for conflict detection.
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
from typing import Any, Dict, List, Optional

import RNS

logger = logging.getLogger(__name__)

# Request paths — must match handlers registered in ReticulumPeerService
PATH_INDEX = "/sync/index"
PATH_FILE  = "/sync/file"

# How long to wait for index/file responses
TIMEOUT_INDEX = 30    # seconds
TIMEOUT_FILE  = 300   # seconds — large files may be slow


@dataclass
class FileRecord:
    path:    str
    size:    int
    mtime:   float
    hash:    str
    version: Dict[str, int] = field(default_factory=dict)

    def to_dict(self):
        return {"path": self.path, "size": self.size,
                "mtime": self.mtime, "hash": self.hash,
                "version": self.version}

    @classmethod
    def from_dict(cls, d):
        return cls(path=d["path"], size=d["size"], mtime=d["mtime"],
                   hash=d.get("hash", ""), version=d.get("version", {}))

    def dominates(self, other):
        keys = set(self.version) | set(other.version)
        return all(self.version.get(k, 0) >= other.version.get(k, 0) for k in keys)

    def conflicts_with(self, other):
        return not self.dominates(other) and not other.dominates(self)


@dataclass
class SyncStatus:
    state:            str = "idle"
    files_local:      int = 0
    files_synced:     int = 0
    active_transfers: int = 0
    last_sync:        Optional[datetime] = None
    errors:           List[str] = field(default_factory=list)


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
    p = os.path.join(store_dir, "index_id")
    try:
        if os.path.exists(p):
            return open(p).read().strip()
    except Exception:
        pass
    idx = uuid.uuid4().hex
    os.makedirs(store_dir, exist_ok=True)
    open(p, "w").write(idx)
    return idx


class SyncEngine:
    """
    Synchronises ~/Sync across all discovered peers using RNS natively.

    On peer discovery → open a link → request their index → compare →
    request missing files → RNS delivers them as Resources → write to disk.

    Also registers index/file generators on ReticulumPeerService so
    remote peers can request OUR files the same way.
    """

    def __init__(self, config, event_bus, reticulum_service,
                 transport_manager=None):
        self.config            = config
        self.event_bus         = event_bus
        self.rns               = reticulum_service   # ReticulumPeerService
        self.transport_manager = transport_manager

        self._running     = False
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._scan_task:  Optional[asyncio.Task] = None
        self._status      = SyncStatus()
        self._lock        = threading.Lock()

        self._local_files: Dict[str, FileRecord] = {}

        # Active links: peer_id → RNS.Link
        self._links: Dict[str, Any] = {}

        self._device_id = config.get("device.id", "unknown")
        self._index_id  = _load_index_id(
            os.path.expanduser("~/.local/share/pcos"))

        # Use container data directory for sync (not visible outside app)
        self._sync_dir = os.path.expanduser("~/.local/share/pcos/container/data")
        self._sync_interval = config.get("sync.sync_interval", 60)
        os.makedirs(self._sync_dir, exist_ok=True)

        # Subscribe to peer events
        self.event_bus.subscribe("peer.discovered", self._on_peer_discovered)
        self.event_bus.subscribe("peer.lost",       self._on_peer_lost)

        logger.info("SyncEngine v3 initialised")

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self):
        if self._running:
            return
        logger.info("Starting sync engine…")
        self._running    = True
        self._event_loop = asyncio.get_event_loop()

        # Register our handlers on the RNS destination
        self.rns.register_index_handler(self._provide_index)
        self.rns.register_file_handler(self._provide_file)

        await self._scan_local_files()
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("Sync engine started")

    async def stop(self):
        logger.info("Stopping sync engine…")
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
            try:
                await self._scan_task
            except asyncio.CancelledError:
                pass
        # Tear down all links
        with self._lock:
            for link in self._links.values():
                try:
                    link.teardown()
                except Exception:
                    pass
            self._links.clear()
        logger.info("Sync engine stopped")

    def is_running(self) -> bool:
        return self._running

    def get_status(self) -> SyncStatus:
        self._status.files_local = len(self._local_files)
        return self._status

    @property
    def sync_dir(self) -> str:
        return self._sync_dir

    # ── Request handlers (called by RNS via ReticulumPeerService) ─────

    def _provide_index(self) -> dict:
        """Return our file index for any peer that requests it."""
        return {p: r.to_dict() for p, r in self._local_files.items()}

    def _provide_file(self, rel_path: str) -> Optional[bytes]:
        """Return file bytes for any peer that requests it."""
        full = os.path.join(self._sync_dir, rel_path)
        if not os.path.exists(full):
            return None
        try:
            with open(full, "rb") as f:
                return f.read()
        except Exception as exc:
            logger.error(f"Error reading {rel_path}: {exc}")
            return None

    # ── Peer event handlers ────────────────────────────────────────────

    async def _on_peer_discovered(self, event):
        peer_id   = event.data.get("id")
        peer_name = event.data.get("name", "unknown")
        if not peer_id:
            return
        logger.info(f"Peer discovered: {peer_name} — syncing")
        await self._sync_with_peer(peer_id, peer_name)

    async def _on_peer_lost(self, event):
        peer_id = event.data.get("id")
        if peer_id:
            with self._lock:
                link = self._links.pop(peer_id, None)
            if link:
                try:
                    link.teardown()
                except Exception:
                    pass

    # ── Periodic scan ──────────────────────────────────────────────────

    async def _scan_loop(self):
        await asyncio.sleep(10)
        while self._running:
            try:
                prev = {p: r.hash for p, r in self._local_files.items()}
                await self._scan_local_files()
                now  = {p: r.hash for p, r in self._local_files.items()}

                if now != prev:
                    # Local files changed — re-sync with all peers
                    logger.info("Local files changed — re-syncing with peers")
                    for peer in self.rns.get_peers():
                        asyncio.create_task(
                            self._sync_with_peer(peer.id, peer.name))

                await asyncio.sleep(self._sync_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Scan loop error: {exc}", exc_info=True)
                await asyncio.sleep(self._sync_interval)

    # ── Core sync flow ─────────────────────────────────────────────────

    async def _sync_with_peer(self, peer_id: str, peer_name: str):
        """
        Full sync cycle with one peer:
          1. Open (or reuse) a link
          2. link.request(PATH_INDEX) → get their index
          3. Compare → find what we need
          4. link.request(PATH_FILE, path) for each missing file
          5. Write received files to ~/Sync/
        """
        link = await self._get_link(peer_id)
        if not link:
            return

        # ── Step 1: Request their index ────────────────────────────────
        logger.info(f"Requesting index from {peer_name}…")
        index_data = await self._request(
            link, PATH_INDEX, data=None, timeout=TIMEOUT_INDEX)

        if index_data is None:
            logger.warning(f"No index response from {peer_name}")
            return

        try:
            remote_index = {
                p: FileRecord.from_dict(d)
                for p, d in json.loads(index_data).items()
            }
        except Exception as exc:
            logger.error(f"Bad index from {peer_name}: {exc}")
            return

        logger.info(f"Got index from {peer_name}: {len(remote_index)} file(s)")

        # ── Step 2: Compute what we need ───────────────────────────────
        needed = self._compute_needed(remote_index)
        if not needed:
            logger.info(f"Already up to date with {peer_name}")
            return
        logger.info(f"Need {len(needed)} file(s) from {peer_name}")

        # ── Step 3: Request each file ──────────────────────────────────
        for rel_path in needed:
            await self._request_file(link, peer_id, peer_name,
                                     rel_path, remote_index[rel_path])

        self._status.last_sync = datetime.now()

    async def _get_link(self, peer_id: str) -> Optional[Any]:
        """Return existing active link or create a new one."""
        with self._lock:
            link = self._links.get(peer_id)

        if link and link.status == RNS.Link.ACTIVE:
            return link

        # Create a new link
        link = self.rns.create_link(peer_id)
        if not link:
            return None

        # Wait for it to become ACTIVE (up to 15s)
        for _ in range(30):
            await asyncio.sleep(0.5)
            if link.status == RNS.Link.ACTIVE:
                break
        else:
            logger.warning(f"Link to {peer_id[:16]} timed out")
            try:
                link.teardown()
            except Exception:
                pass
            return None

        with self._lock:
            self._links[peer_id] = link

        logger.debug(f"Link ACTIVE to {peer_id[:16]}…")
        return link

    async def _request(self, link, path: str, data,
                       timeout: float) -> Optional[bytes]:
        """
        Send a link.request() and await the response.
        Returns response bytes or None on failure/timeout.
        """
        loop    = asyncio.get_event_loop()
        future  = loop.create_future()

        def _on_response(receipt):
            resp = receipt.response
            if resp is None:
                resp = b""
            # receipt.response may be bytes or a stream
            if hasattr(resp, "read"):
                resp = resp.read()
            if not future.done():
                loop.call_soon_threadsafe(future.set_result, resp)

        def _on_failed(receipt):
            if not future.done():
                loop.call_soon_threadsafe(
                    future.set_exception,
                    Exception(f"Request to {path} failed"))

        request_data = json.dumps(data).encode() if data else None

        receipt = link.request(
            path,
            data             = request_data,
            response_callback = _on_response,
            failed_callback   = _on_failed,
            timeout          = timeout,
        )

        if receipt is False:
            logger.error(f"link.request({path}) returned False")
            return None

        try:
            return await asyncio.wait_for(future, timeout=timeout + 5)
        except asyncio.TimeoutError:
            logger.warning(f"Request {path} timed out after {timeout}s")
            return None
        except Exception as exc:
            logger.warning(f"Request {path} failed: {exc}")
            return None

    async def _request_file(self, link, peer_id: str, peer_name: str,
                            rel_path: str, remote_rec: FileRecord):
        """Request one file from a peer and write it to ~/Sync/."""
        logger.info(f"Requesting {rel_path} from {peer_name}…")
        self._status.active_transfers += 1

        try:
            data = await self._request(
                link, PATH_FILE,
                data    = {"path": rel_path},
                timeout = TIMEOUT_FILE,
            )

            if not data:
                logger.warning(f"No data received for {rel_path}")
                return

            # Verify hash
            actual_hash = hashlib.sha256(data).hexdigest()
            if remote_rec.hash and actual_hash != remote_rec.hash:
                logger.error(
                    f"Hash mismatch for {rel_path}: "
                    f"expected {remote_rec.hash[:16]} got {actual_hash[:16]}")
                return

            full_path  = os.path.join(self._sync_dir, rel_path)
            parent_dir = os.path.dirname(full_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # Conflict check
            local_rec = self._local_files.get(rel_path)
            if local_rec and local_rec.version and remote_rec.version:
                incoming = FileRecord(
                    path=rel_path, size=len(data), mtime=time.time(),
                    hash=actual_hash, version=remote_rec.version)
                if incoming.conflicts_with(local_rec):
                    base, ext = os.path.splitext(full_path)
                    conflict  = f"{base}.conflict-{peer_id[:8]}{ext}"
                    try:
                        os.rename(full_path, conflict)
                        logger.warning(
                            f"Conflict: saved existing as "
                            f"{os.path.basename(conflict)}")
                    except Exception:
                        pass

            with open(full_path, "wb") as f:
                f.write(data)

            logger.info(
                f"Received {rel_path} from {peer_name} "
                f"({len(data)/1024:.1f} KB) ✓")
            self._status.files_synced += 1

            # Rescan so new file appears in our index
            await self._scan_local_files()

        finally:
            self._status.active_transfers = max(0, self._status.active_transfers - 1)

    def _compute_needed(self, remote: Dict[str, FileRecord]) -> List[str]:
        needed = []
        for path, remote_rec in remote.items():
            local_rec = self._local_files.get(path)
            if local_rec is None:
                needed.append(path)
                continue
            if remote_rec.hash == local_rec.hash:
                continue
            if remote_rec.version and local_rec.version:
                if remote_rec.dominates(local_rec):
                    needed.append(path)
                elif remote_rec.conflicts_with(local_rec):
                    logger.warning(f"Conflict for {path} — requesting both")
                    needed.append(path)
            elif remote_rec.mtime > local_rec.mtime:
                needed.append(path)
        return needed

    # ── File scanning ──────────────────────────────────────────────────

    async def _scan_local_files(self):
        logger.debug("Scanning local files…")
        new_files: Dict[str, FileRecord] = {}
        for root, dirs, files in os.walk(self._sync_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                if fname.startswith("."):
                    continue
                fp  = os.path.join(root, fname)
                rel = os.path.relpath(fp, self._sync_dir)
                try:
                    st   = os.stat(fp)
                    fhash = _sha256(fp)
                    existing = self._local_files.get(rel)
                    if existing and existing.hash == fhash:
                        version = existing.version
                    else:
                        version = dict(existing.version if existing else {})
                        version[self._device_id] = \
                            version.get(self._device_id, 0) + 1
                    new_files[rel] = FileRecord(
                        path=rel, size=st.st_size,
                        mtime=st.st_mtime, hash=fhash, version=version)
                except Exception as exc:
                    logger.warning(f"Scan error {fp}: {exc}")
        self._local_files = new_files
        self._status.files_local = len(new_files)
        logger.info(f"Found {len(new_files)} local file(s)")
