"""
Peer Link Service - Encrypted P2P Links via Reticulum

Manages RNS.Link objects to peers.  Uses raw RNS.Packet for all data
transfer — Channel/Buffer is intentionally avoided because it adds
complexity without benefit for the message sizes used in this app.

Sending:   RNS.Packet(link, data, context=RNS.Packet.DATA).send()
Receiving: link.set_packet_callback(cb)  — cb(message: bytes, packet)

For data larger than RNS.Link.MDU (431 bytes) the sender fragments into
numbered chunks and the receiver reassembles.  In practice sync control
messages (JSON) fit comfortably within one packet; file data goes through
RNS.Resource (handled in sync.py), not through this service.
"""
import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import RNS

logger = logging.getLogger(__name__)

# Maximum bytes per raw RNS packet (link MDU minus a small framing header)
# We leave 16 bytes headroom for the chunk framing prefix.
_CHUNK_OVERHEAD = 16
_MAX_CHUNK = RNS.Link.MDU - _CHUNK_OVERHEAD   # ~415 bytes

# Chunk framing: 4-byte big-endian prefix  <seq: 2 bytes><total: 2 bytes>
# seq   = chunk index (0-based)
# total = total number of chunks
import struct
_FRAME_FMT  = ">HH"
_FRAME_SIZE = struct.calcsize(_FRAME_FMT)  # 4 bytes


class LinkState(Enum):
    IDLE         = "idle"
    CONNECTING   = "connecting"
    CONNECTED    = "connected"
    DISCONNECTED = "disconnected"
    ERROR        = "error"


@dataclass
class LinkInfo:
    peer_id:       str
    peer_name:     str
    state:         LinkState = LinkState.IDLE
    established:   Optional[datetime] = None
    bytes_sent:    int = 0
    bytes_received: int = 0
    last_activity: Optional[datetime] = None


class PeerLinkService:
    """
    Manages encrypted RNS.Link connections to discovered peers.

    Public API
    ----------
    connect_to_peer(peer_id)          → bool
    disconnect_from_peer(peer_id)
    send_to_peer(peer_id, data)       → bool
    send_json_to_peer(peer_id, obj)   → bool
    send_text_to_peer(peer_id, text)  → bool
    broadcast(data)                   → int  (count of peers reached)
    register_data_callback(peer_id, cb)
    register_link_callback(cb)
    is_connected_to(peer_id)          → bool
    get_connected_peers()             → List[str]
    get_link_info(peer_id)            → Optional[LinkInfo]
    """

    def __init__(self, config, event_bus, reticulum_service):
        self.config = config
        self.event_bus = event_bus
        self._reticulum_service = reticulum_service

        self._links:       Dict[str, Any]        = {}   # peer_id → RNS.Link
        self._link_info:   Dict[str, LinkInfo]   = {}
        self._link_profiles: Dict[str, Any]      = {}   # peer_id → LinkProfile (from detector)

        # per-peer reassembly buffers: peer_id → {total: int, chunks: {seq: bytes}}
        self._reassembly:  Dict[str, Dict]       = {}

        self._data_callbacks: Dict[str, Callable] = {}  # peer_id → cb(peer_id, bytes)
        self._link_callbacks: List[Callable]      = []  # cb(peer_id, LinkState)

        self._lock    = threading.Lock()
        self._running = False

        logger.info("PeerLinkService initialised")

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self):
        if self._running:
            return
        self._running = True
        logger.info("Peer link service started")

    async def stop(self):
        logger.info("Stopping peer link service…")
        self._running = False
        with self._lock:
            for peer_id, link in list(self._links.items()):
                try:
                    link.teardown()
                except Exception:
                    pass
            self._links.clear()
            self._link_info.clear()
            self._link_profiles.clear()
            self._reassembly.clear()
        logger.info("Peer link service stopped")

    # ------------------------------------------------------------------ #
    # Connection management                                                #
    # ------------------------------------------------------------------ #

    def connect_to_peer(self, peer_id: str) -> bool:
        """
        Open an RNS.Link to peer_id.  Returns True if the link object
        was created (it will become ACTIVE asynchronously via the
        _on_link_established callback).
        """
        if not self._reticulum_service:
            logger.error("Reticulum service not available")
            return False

        with self._lock:
            if peer_id in self._links:
                return True

            peer      = self._reticulum_service.get_peer(peer_id)
            peer_name = peer.name if peer else "unknown"
            self._link_info[peer_id] = LinkInfo(
                peer_id=peer_id, peer_name=peer_name,
                state=LinkState.CONNECTING)

            try:
                link = self._reticulum_service.create_link(peer_id)
                if not link:
                    logger.error(f"create_link returned None for {peer_id}")
                    self._link_info[peer_id].state = LinkState.ERROR
                    return False

                link.set_link_established_callback(self._on_link_established)
                link.set_link_closed_callback(self._on_link_closed)
                # packet callback registered in _on_link_established once ACTIVE

                self._links[peer_id] = link
                logger.info(f"Connecting to peer: {peer_name}")
                return True

            except Exception as exc:
                logger.error(f"Error connecting to {peer_id}: {exc}", exc_info=True)
                self._link_info[peer_id].state = LinkState.ERROR
                return False

    def disconnect_from_peer(self, peer_id: str):
        with self._lock:
            link = self._links.pop(peer_id, None)
            self._link_profiles.pop(peer_id, None)
            self._reassembly.pop(peer_id, None)
            if peer_id in self._link_info:
                self._link_info[peer_id].state = LinkState.DISCONNECTED
        if link:
            try:
                link.teardown()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Sending                                                              #
    # ------------------------------------------------------------------ #

    def send_to_peer(self, peer_id: str, data: bytes) -> bool:
        """
        Send raw bytes to a peer.  Fragments automatically if len(data)
        exceeds _MAX_CHUNK.  Returns True if all packets were queued.
        """
        with self._lock:
            link = self._links.get(peer_id)

        if not link:
            logger.warning(f"send_to_peer: no link for {peer_id}")
            return False
        if link.status != RNS.Link.ACTIVE:
            logger.warning(f"send_to_peer: link to {peer_id} not ACTIVE (status={link.status})")
            return False

        # Fragment
        chunk_size = _MAX_CHUNK - _FRAME_SIZE
        chunks = [data[i:i+chunk_size] for i in range(0, len(data), chunk_size)]
        total  = len(chunks)

        try:
            for seq, chunk in enumerate(chunks):
                frame = struct.pack(_FRAME_FMT, seq, total) + chunk
                packet = RNS.Packet(link, frame, context=RNS.Packet.DATA)
                receipt = packet.send()
                if receipt is False:
                    logger.error(f"Packet send failed (seq {seq}/{total}) to {peer_id}")
                    return False

            info = self._link_info.get(peer_id)
            if info:
                info.bytes_sent     += len(data)
                info.last_activity   = datetime.now()

            return True

        except Exception as exc:
            logger.error(f"send_to_peer error for {peer_id}: {exc}", exc_info=True)
            return False

    def send_json_to_peer(self, peer_id: str, obj: dict) -> bool:
        try:
            return self.send_to_peer(peer_id, json.dumps(obj).encode())
        except Exception as exc:
            logger.error(f"send_json_to_peer error: {exc}")
            return False

    def send_text_to_peer(self, peer_id: str, text: str) -> bool:
        return self.send_to_peer(peer_id, text.encode("utf-8"))

    def broadcast(self, data: bytes) -> int:
        with self._lock:
            peers = [pid for pid, l in self._links.items()
                     if l.status == RNS.Link.ACTIVE]
        count = 0
        for peer_id in peers:
            if self.send_to_peer(peer_id, data):
                count += 1
        return count

    # ------------------------------------------------------------------ #
    # Callback registration                                                #
    # ------------------------------------------------------------------ #

    def register_data_callback(self, peer_id: str, callback: Callable):
        """Register callback(peer_id, data: bytes) for inbound data from peer_id."""
        self._data_callbacks[peer_id] = callback

    def register_link_callback(self, callback: Callable):
        """Register callback(peer_id, LinkState) for link state changes."""
        self._link_callbacks.append(callback)

    # ------------------------------------------------------------------ #
    # RNS callbacks (called from RNS background threads)                  #
    # ------------------------------------------------------------------ #

    def _on_link_established(self, link):
        """Called by RNS when a link becomes ACTIVE."""
        peer_id = self._peer_id_for_link(link)
        if peer_id is None:
            # Could be an inbound link registered by reticulum_peer._on_inbound_link
            # that wasn't in our _links dict yet — search by object identity
            logger.warning("_on_link_established: link not found in _links")
            return

        with self._lock:
            info = self._link_info.get(peer_id)
            if info:
                info.state       = LinkState.CONNECTED
                info.established = datetime.now()
                info.last_activity = datetime.now()

        # Register the packet receive callback NOW that the link is ACTIVE
        # Signature must be (message: bytes, packet: RNS.Packet)
        link.set_packet_callback(
            lambda msg, pkt, pid=peer_id: self._on_packet_received(pid, msg, pkt)
        )

        # Classify the link and store the profile
        try:
            from transport.detector import classify_link
            peer = self._reticulum_service.get_peer(peer_id) if self._reticulum_service else None
            name = peer.name if peer else peer_id[:12]
            profile = classify_link(link, peer_id, name)
            with self._lock:
                self._link_profiles[peer_id] = profile
        except Exception as exc:
            logger.debug(f"Could not classify link: {exc}")

        logger.info(f"Link established with peer: {peer_id[:16]}…")

        for cb in self._link_callbacks:
            try:
                cb(peer_id, LinkState.CONNECTED)
            except Exception as exc:
                logger.error(f"Link callback error: {exc}")

    def _on_link_closed(self, link):
        """Called by RNS when a link is torn down."""
        peer_id = self._peer_id_for_link(link)
        if peer_id:
            with self._lock:
                self._links.pop(peer_id, None)
                self._link_profiles.pop(peer_id, None)
                self._reassembly.pop(peer_id, None)
                if peer_id in self._link_info:
                    self._link_info[peer_id].state = LinkState.DISCONNECTED

            logger.info(f"Link closed with peer: {peer_id[:16]}…")

            for cb in self._link_callbacks:
                try:
                    cb(peer_id, LinkState.DISCONNECTED)
                except Exception as exc:
                    logger.error(f"Link callback error: {exc}")

    def _on_packet_received(self, peer_id: str, message: bytes, packet):
        """
        Called from an RNS background thread when a DATA packet arrives.

        Handles reassembly of fragmented messages, then dispatches the
        complete payload to the registered data callback.
        """
        if not message or len(message) < _FRAME_SIZE:
            logger.debug(f"Received undersized packet from {peer_id}")
            return

        try:
            seq, total = struct.unpack(_FRAME_FMT, message[:_FRAME_SIZE])
            payload = message[_FRAME_SIZE:]
        except struct.error as exc:
            logger.error(f"Bad packet framing from {peer_id}: {exc}")
            return

        # Update stats
        with self._lock:
            info = self._link_info.get(peer_id)
            if info:
                info.bytes_received += len(message)
                info.last_activity   = datetime.now()

        # Single-packet message (common case)
        if total == 1:
            self._dispatch(peer_id, payload)
            return

        # Multi-packet reassembly
        with self._lock:
            if peer_id not in self._reassembly:
                self._reassembly[peer_id] = {"total": total, "chunks": {}}
            buf = self._reassembly[peer_id]

            # Reset if a new message starts mid-reassembly
            if buf["total"] != total:
                buf["total"]  = total
                buf["chunks"] = {}

            buf["chunks"][seq] = payload

            if len(buf["chunks"]) == total:
                # All chunks received — reassemble in order
                data = b"".join(buf["chunks"][i] for i in range(total))
                del self._reassembly[peer_id]
            else:
                data = None

        if data is not None:
            self._dispatch(peer_id, data)

    def _dispatch(self, peer_id: str, data: bytes):
        """Invoke the registered data callback for peer_id (outside the lock)."""
        cb = self._data_callbacks.get(peer_id)
        if cb:
            try:
                cb(peer_id, data)
            except Exception as exc:
                logger.error(f"Data callback error for {peer_id}: {exc}", exc_info=True)
        else:
            logger.debug(f"No data callback for peer {peer_id[:16]}…, dropping {len(data)} bytes")

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _peer_id_for_link(self, link) -> Optional[str]:
        """Find the peer_id whose link object is `link`."""
        with self._lock:
            for pid, l in self._links.items():
                if l is link:
                    return pid
        return None

    # ------------------------------------------------------------------ #
    # Queries                                                              #
    # ------------------------------------------------------------------ #

    def is_connected_to(self, peer_id: str) -> bool:
        with self._lock:
            link = self._links.get(peer_id)
        return link is not None and link.status == RNS.Link.ACTIVE

    def get_connected_peers(self) -> List[str]:
        with self._lock:
            return [pid for pid, l in self._links.items()
                    if l.status == RNS.Link.ACTIVE]

    def get_link_info(self, peer_id: str) -> Optional[LinkInfo]:
        with self._lock:
            return self._link_info.get(peer_id)

    def get_all_link_info(self) -> Dict[str, LinkInfo]:
        with self._lock:
            return dict(self._link_info)

    def get_link_profile(self, peer_id: str) -> Optional[Any]:
        """Return the LinkProfile (transport tier) for a peer, if available."""
        with self._lock:
            return self._link_profiles.get(peer_id)
