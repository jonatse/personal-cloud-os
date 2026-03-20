"""
Reticulum Peer Service

Handles RNS initialisation, peer discovery via announces, and
registers request handlers on our destination so peers can request
our file index and files directly — no custom packet routing needed.

RNS does the heavy lifting:
  - destination.register_request_handler() routes inbound requests by path
  - link.request() sends requests with built-in retry/timeout
  - RNS.Resource handles all chunking/windowing for large responses
  - No set_packet_callback, no inbound link hacks, no _route_packet
"""
import asyncio
import json
import logging
import os
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import RNS

logger = logging.getLogger(__name__)

APP_NAME         = "personalcloudos"
PEER_ASPECT      = "peers"
PATH_INDEX       = "/sync/index"    # handler: return our file index
PATH_FILE        = "/sync/file"     # handler: return file bytes by path


@dataclass
class Peer:
    id:          str           # destination hash hex
    name:        str
    destination: Any           # RNS.Destination (OUT, for creating links)
    last_seen:   datetime = field(default_factory=datetime.now)

    def to_dict(self):
        return {"id": self.id, "name": self.name,
                "last_seen": self.last_seen.isoformat()}


class ReticulumPeerService:
    """
    Manages RNS stack, identity, peer discovery, and request handlers.

    SyncEngine registers its index/file generators here at start() time.
    Everything else — link establishment, request routing, Resource
    transfer — is handled by RNS itself.
    """

    def __init__(self, config, event_bus):
        self.config     = config
        self.event_bus  = event_bus

        self._reticulum:   Optional[Any] = None
        self._identity:    Optional[Any] = None
        self._destination: Optional[Any] = None

        self._peers: Dict[str, Peer] = {}
        self._lock  = threading.Lock()

        self._running          = False
        self._event_loop:      Optional[asyncio.AbstractEventLoop] = None
        self._announce_interval = config.get("reticulum.announce_interval", 30)
        self._peer_timeout      = config.get("reticulum.peer_timeout", 300)

        # Callbacks registered by SyncEngine
        self._index_generator: Optional[Callable] = None  # () -> dict
        self._file_generator:  Optional[Callable] = None  # (path) -> bytes|None

        self._identity_path = config.get(
            "reticulum.identity_path",
            os.path.expanduser("~/.reticulum/storage/identities/pcos"))

        logger.info("ReticulumPeerService initialised")

    # ── Registration API (called by SyncEngine before start) ──────────

    def register_index_handler(self, fn: Callable):
        """Register fn() -> dict that returns our current file index."""
        self._index_generator = fn

    def register_file_handler(self, fn: Callable):
        """Register fn(path: str) -> bytes|None that returns file data."""
        self._file_generator = fn

    # ── Lifecycle ──────────────────────────────────────────────────────

    async def start(self):
        if self._running:
            return
        logger.info("Starting Reticulum peer service…")
        self._running    = True
        self._event_loop = asyncio.get_event_loop()

        await self._init_rns()

        threading.Thread(target=self._announce_loop,
                         daemon=True, name="rns-announce").start()
        threading.Thread(target=self._expiry_loop,
                         daemon=True, name="rns-expiry").start()

        logger.info(f"RNS started — identity: {self._identity.hash.hex()[:16]}…")
        logger.info(f"Destination: {self._destination.hash.hex()[:16]}…")

    async def stop(self):
        logger.info("Stopping Reticulum peer service…")
        self._running = False

    def is_running(self) -> bool:
        return self._running

    # ── RNS initialisation ─────────────────────────────────────────────

    async def _init_rns(self):
        config_path = os.path.expanduser("~/.reticulum")
        self._reticulum = RNS.Reticulum(config_path)

        # Load or create persistent identity
        id_file = os.path.expanduser(self._identity_path)
        if os.path.exists(id_file):
            self._identity = RNS.Identity.from_file(id_file)
            logger.info(f"Loaded identity: {self._identity.hash.hex()[:16]}…")
        else:
            self._identity = RNS.Identity()
            os.makedirs(os.path.dirname(id_file), exist_ok=True)
            self._identity.to_file(id_file)
            logger.info("Created new identity")

        # Our single IN destination — peers open links to this
        self._destination = RNS.Destination(
            self._identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            APP_NAME,
            PEER_ASPECT,
        )
        self._destination.set_proof_strategy(RNS.Destination.PROVE_ALL)

        # Register request handlers — RNS routes inbound requests here
        # automatically regardless of which link they arrive on.
        self._destination.register_request_handler(
            path               = PATH_INDEX,
            response_generator = self._handle_index_request,
            allow              = RNS.Destination.ALLOW_ALL,
        )
        self._destination.register_request_handler(
            path               = PATH_FILE,
            response_generator = self._handle_file_request,
            allow              = RNS.Destination.ALLOW_ALL,
        )

        logger.info("Request handlers registered: /sync/index, /sync/file")

        # Announce handler so we discover other PCOS devices
        class _AnnounceHandler:
            aspect_filter = f"{APP_NAME}.{PEER_ASPECT}"
            def __init__(self, svc): self.svc = svc
            def received_announce(self, dest_hash, identity, app_data):
                self.svc._on_announce(dest_hash, identity, app_data)

        RNS.Transport.register_announce_handler(_AnnounceHandler(self))
        logger.info(f"Announce handler registered for {APP_NAME}.{PEER_ASPECT}")

    # ── Request handlers (called by RNS from background threads) ──────

    def _handle_index_request(self, path, data, req_id,
                               link_id, remote_identity, requested_at):
        """Return our file index as msgpack-able bytes."""
        try:
            if self._index_generator:
                index = self._index_generator()
                payload = json.dumps(index).encode()
                logger.info(f"Index requested — returning {len(index)} files")
                return payload
        except Exception as exc:
            logger.error(f"Index handler error: {exc}", exc_info=True)
        return b"{}"

    def _handle_file_request(self, path, data, req_id,
                              link_id, remote_identity, requested_at):
        """Return file bytes for the requested path."""
        try:
            req_path = None
            if data:
                req_path = json.loads(data).get("path") if isinstance(data, (bytes, str)) else None
            if not req_path:
                logger.warning("File request with no path")
                return None
            if self._file_generator:
                file_data = self._file_generator(req_path)
                if file_data is not None:
                    logger.info(f"File requested: {req_path} ({len(file_data)/1024:.1f} KB)")
                    return file_data
                else:
                    logger.warning(f"File not found: {req_path}")
        except Exception as exc:
            logger.error(f"File handler error: {exc}", exc_info=True)
        return None

    # ── Announce / peer discovery ──────────────────────────────────────

    def _announce_loop(self):
        hostname = socket.gethostname()
        app_data = json.dumps({"name": hostname}).encode()
        while self._running:
            try:
                self._destination.announce(app_data=app_data)
                logger.debug(f"Announced as {hostname}")
            except Exception as exc:
                logger.error(f"Announce error: {exc}")
            for _ in range(self._announce_interval * 10):
                if not self._running:
                    break
                time.sleep(0.1)

    def _on_announce(self, dest_hash, identity, app_data):
        """Called by RNS when another PCOS device announces."""
        peer_hash = dest_hash.hex() if hasattr(dest_hash, "hex") else str(dest_hash)

        # Ignore our own announces
        if peer_hash == self._destination.hash.hex():
            return

        name = "unknown"
        try:
            if app_data:
                name = json.loads(app_data).get("name", "unknown")
        except Exception:
            pass

        with self._lock:
            is_new = peer_hash not in self._peers
            if is_new:
                # Build an OUT destination for creating links to this peer
                out_dest = RNS.Destination(
                    identity,
                    RNS.Destination.OUT,
                    RNS.Destination.SINGLE,
                    APP_NAME,
                    PEER_ASPECT,
                )
                self._peers[peer_hash] = Peer(
                    id=peer_hash, name=name, destination=out_dest)
            else:
                self._peers[peer_hash].last_seen = datetime.now()
                self._peers[peer_hash].name      = name

        if is_new:
            logger.info(f"Discovered peer: {name} ({peer_hash[:16]}…)")
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    self._publish_event("peer.discovered",
                                        {"id": peer_hash, "name": name}),
                    self._event_loop)
        else:
            logger.debug(f"Peer heartbeat: {name}")

    def _expiry_loop(self):
        """Remove peers that haven't announced recently."""
        while self._running:
            time.sleep(self._peer_timeout / 2)
            now = datetime.now()
            expired = []
            with self._lock:
                for pid, peer in list(self._peers.items()):
                    age = (now - peer.last_seen).total_seconds()
                    if age > self._peer_timeout:
                        expired.append(pid)
            for pid in expired:
                with self._lock:
                    peer = self._peers.pop(pid, None)
                if peer:
                    logger.info(f"Peer expired: {peer.name}")
                    if self._event_loop:
                        asyncio.run_coroutine_threadsafe(
                            self._publish_event("peer.lost",
                                                {"id": pid, "name": peer.name}),
                            self._event_loop)

    # ── Link creation (used by SyncEngine) ────────────────────────────

    def create_link(self, peer_id: str) -> Optional[Any]:
        """Create an outbound RNS.Link to peer_id's destination."""
        with self._lock:
            peer = self._peers.get(peer_id)
        if not peer:
            logger.warning(f"create_link: peer {peer_id[:16]} not found")
            return None
        try:
            link = RNS.Link(peer.destination)
            logger.info(f"Created link to {peer.name}")
            return link
        except Exception as exc:
            logger.error(f"create_link error: {exc}", exc_info=True)
            return None

    # ── Queries ────────────────────────────────────────────────────────

    def get_peers(self) -> List[Peer]:
        with self._lock:
            return list(self._peers.values())

    def get_peer(self, peer_id: str) -> Optional[Peer]:
        with self._lock:
            return self._peers.get(peer_id)

    # ── Event publishing ───────────────────────────────────────────────

    async def _publish_event(self, event_type: str, data: dict):
        try:
            from core.events import Event
            await self.event_bus.publish(Event(type=event_type, data=data,
                                               source="reticulum"))
        except Exception as exc:
            logger.error(f"Event publish error: {exc}")
