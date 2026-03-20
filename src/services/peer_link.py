"""
Peer Link Service - Encrypted P2P Links via Reticulum

Provides encrypted peer-to-peer communication using Reticulum links.
- Establishes encrypted links to discovered peers
- Sends/receives messages and files
- Handles link lifecycle
"""
import json
import logging
import threading
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import RNS

logger = logging.getLogger(__name__)


class LinkState(Enum):
    """Link connection state."""
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class LinkInfo:
    """Information about a peer link."""
    def __init__(self, peer_id: str, peer_name: str):
        self.peer_id = peer_id
        self.peer_name = peer_name
        self.state: LinkState = LinkState.IDLE
        self.established: Optional[datetime] = None
        self.bytes_sent: int = 0
        self.bytes_received: int = 0
        self.last_activity: Optional[datetime] = None


class PeerLinkService:
    """
    Manages encrypted P2P links to peers via Reticulum.

    This service:
    - Creates encrypted links to discovered peers
    - Sends/receives data over links using RNS Channel + Buffer
    - Handles link lifecycle
    - Provides callbacks for incoming data
    """

    def __init__(self, config, event_bus, reticulum_service):
        """Initialize the peer link service."""
        self.config = config
        self.event_bus = event_bus
        self._reticulum_service = reticulum_service

        # Active links: peer_id -> RNS.Link
        self._links: Dict[str, Any] = {}
        self._link_info: Dict[str, LinkInfo] = {}

        # Per-peer Channel Buffer (BufferedRWPair), created only after link is ACTIVE
        self._buffers: Dict[str, Any] = {}

        # Callbacks
        self._data_callbacks: Dict[str, Callable] = {}   # peer_id -> callback(peer_id, data)
        self._link_callbacks: List[Callable] = []         # callback(peer_id, LinkState)

        # Lock for thread safety (RNS callbacks fire from RNS threads)
        self._lock = threading.Lock()

        self._running = False

        logger.info("PeerLinkService initialized")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start the peer link service."""
        if self._running:
            return
        logger.info("Starting peer link service...")
        self._running = True
        logger.info("Peer link service started")

    async def stop(self):
        """Stop the peer link service and tear down all links."""
        logger.info("Stopping peer link service...")
        self._running = False

        with self._lock:
            # Close buffers first
            for peer_id, buf in list(self._buffers.items()):
                try:
                    buf.close()
                except Exception as e:
                    logger.debug(f"Error closing buffer for {peer_id}: {e}")
            self._buffers.clear()

            # Tear down links
            for peer_id, link in list(self._links.items()):
                try:
                    link.teardown()
                except Exception as e:
                    logger.debug(f"Error closing link to {peer_id}: {e}")
            self._links.clear()
            self._link_info.clear()

        logger.info("Peer link service stopped")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect_to_peer(self, peer_id: str) -> bool:
        """
        Establish an encrypted link to a peer.

        Returns True if a link object was created (not yet necessarily active),
        False on error.
        """
        if not self._reticulum_service:
            logger.error("Reticulum service not available")
            return False

        with self._lock:
            if peer_id in self._links:
                logger.debug(f"Already have a link to peer: {peer_id}")
                return True

            peer = self._reticulum_service.get_peer(peer_id)
            peer_name = peer.name if peer else "Unknown"

            self._link_info[peer_id] = LinkInfo(peer_id=peer_id, peer_name=peer_name)
            self._link_info[peer_id].state = LinkState.CONNECTING

            try:
                link = self._reticulum_service.create_link(peer_id)
                if not link:
                    logger.error(f"Failed to create link to peer: {peer_id}")
                    self._link_info[peer_id].state = LinkState.ERROR
                    return False

                # Register lifecycle and receive callbacks.
                # NOTE: We do NOT use set_packet_callback here because we are
                # sending via Channel/Buffer (context=CHANNEL).  Raw packet
                # callbacks only fire for context=NONE packets.  Inbound data
                # is handled by the buffer ready_callback set up in
                # _on_link_established once the link is ACTIVE.
                link.set_link_established_callback(self._on_link_established)
                link.set_link_closed_callback(self._on_link_closed)

                self._links[peer_id] = link
                logger.info(f"Connecting to peer: {peer_name}")
                return True

            except Exception as e:
                logger.error(f"Error connecting to peer {peer_id}: {e}", exc_info=True)
                if peer_id in self._link_info:
                    self._link_info[peer_id].state = LinkState.ERROR
                return False

    def disconnect_from_peer(self, peer_id: str):
        """Close link to a peer and clean up its buffer."""
        with self._lock:
            # Clean up buffer
            if peer_id in self._buffers:
                try:
                    self._buffers[peer_id].close()
                except Exception as e:
                    logger.debug(f"Error closing buffer for {peer_id}: {e}")
                del self._buffers[peer_id]

            # Tear down link
            if peer_id in self._links:
                try:
                    self._links[peer_id].teardown()
                except Exception as e:
                    logger.debug(f"Error closing link to {peer_id}: {e}")
                del self._links[peer_id]

                if peer_id in self._link_info:
                    self._link_info[peer_id].state = LinkState.DISCONNECTED
                logger.info(f"Disconnected from peer: {peer_id}")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send_to_peer(self, peer_id: str, data: bytes) -> bool:
        """
        Send raw bytes to a peer over the established Channel/Buffer.

        The link must be ACTIVE (i.e. _on_link_established must have fired)
        before this can succeed.  Returns True on success, False otherwise.
        """
        with self._lock:
            if peer_id not in self._links:
                logger.warning(f"No link to peer: {peer_id}")
                return False

            link = self._links[peer_id]
            if link.status != RNS.Link.ACTIVE:
                logger.warning(
                    f"Link to {peer_id} is not yet ACTIVE (status={link.status}), "
                    "cannot send"
                )
                return False

            if peer_id not in self._buffers:
                logger.warning(f"No buffer for peer {peer_id} (link active but buffer missing?)")
                return False

            buf = self._buffers[peer_id]
            try:
                # Write in a loop in case the underlying writer accepts fewer
                # bytes than requested (max one MDU per RNS.Packet).
                view = memoryview(data)
                total = len(data)
                sent = 0
                while sent < total:
                    n = buf.write(view[sent:])
                    if n is None or n == 0:
                        logger.error(f"Buffer write returned {n} for peer {peer_id}")
                        return False
                    sent += n
                buf.flush()

                if peer_id in self._link_info:
                    self._link_info[peer_id].bytes_sent += total
                    self._link_info[peer_id].last_activity = datetime.now()

                return True

            except Exception as e:
                logger.error(f"Error sending to peer {peer_id}: {e}", exc_info=True)
                return False

    def send_text_to_peer(self, peer_id: str, text: str) -> bool:
        """Send a UTF-8 string to a peer."""
        return self.send_to_peer(peer_id, text.encode("utf-8"))

    def send_json_to_peer(self, peer_id: str, data: dict) -> bool:
        """Serialize *data* to JSON and send it to a peer."""
        try:
            return self.send_to_peer(peer_id, json.dumps(data).encode("utf-8"))
        except Exception as e:
            logger.error(f"Error encoding JSON for peer {peer_id}: {e}")
            return False

    def broadcast(self, data: bytes) -> int:
        """
        Send *data* to every currently ACTIVE peer.

        Returns the number of peers successfully written to.
        """
        count = 0
        # Snapshot peer list outside the per-send lock to avoid double-locking
        with self._lock:
            peer_ids = list(self._links.keys())

        for peer_id in peer_ids:
            if self.send_to_peer(peer_id, data):
                count += 1
        return count

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def register_data_callback(self, peer_id: str, callback: Callable):
        """Register *callback(peer_id, data: bytes)* for incoming data from *peer_id*."""
        self._data_callbacks[peer_id] = callback

    def register_link_callback(self, callback: Callable):
        """Register *callback(peer_id, LinkState)* for link state changes."""
        self._link_callbacks.append(callback)

    # ------------------------------------------------------------------
    # RNS callbacks (called from RNS background threads)
    # ------------------------------------------------------------------

    def _on_link_established(self, link):
        """
        Called by RNS when a link transitions to ACTIVE.

        This is the only safe place to call link.get_channel() because
        link.rtt is set before this callback fires.
        """
        peer_id = None
        with self._lock:
            for pid, l in self._links.items():
                if l is link:
                    peer_id = pid
                    break

            if peer_id is None:
                logger.warning("_on_link_established called for unknown link")
                return

            # Update state
            info = self._link_info.get(peer_id)
            if info:
                info.state = LinkState.CONNECTED
                info.established = datetime.now()
                info.last_activity = datetime.now()

            # Create Channel + Buffer now that the link is ACTIVE.
            # Use a closure so the ready callback knows which peer fired.
            try:
                channel = link.get_channel()
                buf = RNS.Buffer.create_bidirectional_buffer(
                    0, 0, channel,
                    lambda n, pid=peer_id: self._on_buffer_ready(pid, n)
                )
                self._buffers[peer_id] = buf
                logger.debug(f"Channel/Buffer created for peer {peer_id}")
            except Exception as e:
                logger.error(
                    f"Failed to create Channel/Buffer for peer {peer_id}: {e}",
                    exc_info=True
                )

        logger.info(f"Link established with peer: {peer_id}")

        for cb in self._link_callbacks:
            try:
                cb(peer_id, LinkState.CONNECTED)
            except Exception as e:
                logger.error(f"Link callback error: {e}")

    def _on_link_closed(self, link):
        """Called by RNS when a link is torn down."""
        peer_id = None
        with self._lock:
            for pid, l in self._links.items():
                if l is link:
                    peer_id = pid
                    break
            if peer_id:
                # Clean up buffer
                if peer_id in self._buffers:
                    try:
                        self._buffers[peer_id].close()
                    except Exception:
                        pass
                    del self._buffers[peer_id]

                del self._links[peer_id]
                if peer_id in self._link_info:
                    self._link_info[peer_id].state = LinkState.DISCONNECTED

        if peer_id:
            logger.info(f"Link closed with peer: {peer_id}")
            for cb in self._link_callbacks:
                try:
                    cb(peer_id, LinkState.DISCONNECTED)
                except Exception as e:
                    logger.error(f"Link callback error: {e}")

    def _on_buffer_ready(self, peer_id: str, ready_bytes: int):
        """
        Called by RNS (from a background thread) when inbound data is available
        on the Channel/Buffer for *peer_id*.

        Reads all available data and dispatches it to the registered
        data callback for that peer.
        """
        with self._lock:
            buf = self._buffers.get(peer_id)
            if buf is None:
                return

            try:
                data = buf.read(ready_bytes)
            except Exception as e:
                logger.error(f"Error reading from buffer for {peer_id}: {e}")
                return

            info = self._link_info.get(peer_id)
            if info and data:
                info.bytes_received += len(data)
                info.last_activity = datetime.now()

            callback = self._data_callbacks.get(peer_id)

        # Invoke callback outside the lock to avoid deadlocks
        if data and callback:
            try:
                callback(peer_id, data)
            except Exception as e:
                logger.error(f"Data callback error for {peer_id}: {e}")

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_connected_to(self, peer_id: str) -> bool:
        """Return True if we have an ACTIVE link to *peer_id*."""
        with self._lock:
            link = self._links.get(peer_id)
            return link is not None and link.status == RNS.Link.ACTIVE

    def get_connected_peers(self) -> List[str]:
        """Return list of peer IDs with ACTIVE links."""
        with self._lock:
            return [
                pid for pid, l in self._links.items()
                if l.status == RNS.Link.ACTIVE
            ]

    def get_link_info(self, peer_id: str) -> Optional[LinkInfo]:
        """Get link information for a peer."""
        with self._lock:
            return self._link_info.get(peer_id)

    def get_all_link_info(self) -> Dict[str, LinkInfo]:
        """Get link info for all peers."""
        with self._lock:
            return dict(self._link_info)
