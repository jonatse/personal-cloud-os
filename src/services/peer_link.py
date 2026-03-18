"""
Peer Link Service - Encrypted P2P Links via Reticulum

Provides encrypted peer-to-peer communication using Reticulum links.
- Establishes encrypted links to discovered peers
- Sends/receives messages and files
- Handles link lifecycle
"""
import asyncio
import logging
import threading
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class LinkState(Enum):
    """Link connection state."""
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class LinkInfo:
    """Information about a peer link."""
    peer_id: str
    peer_name: str
    state: LinkState = LinkState.IDLE
    established: datetime = None
    bytes_sent: int = 0
    bytes_received: int = 0
    last_activity: datetime = None


class PeerLinkService:
    """
    Manages encrypted P2P links to peers via Reticulum.
    
    This service:
    - Creates encrypted links to discovered peers
    - Sends/receives data over links
    - Handles link lifecycle
    - Provides callbacks for incoming data
    """
    
    def __init__(self, config, event_bus, reticulum_service):
        """Initialize the peer link service."""
        self.config = config
        self.event_bus = event_bus
        self._reticulum_service = reticulum_service
        
        # Active links
        self._links: Dict[str, Any] = {}  # peer_id -> RNS.Link
        self._link_info: Dict[str, LinkInfo] = {}
        
        # Callbacks
        self._data_callbacks: Dict[str, Callable] = {}  # peer_id -> callback
        self._link_callbacks: List[Callable] = []  # Called on link state changes
        
        # Lock for thread safety
        self._lock = threading.Lock()
        
        # State
        self._running = False
        
        logger.info("PeerLinkService initialized")
    
    async def start(self):
        """Start the peer link service."""
        if self._running:
            return
        
        logger.info("Starting peer link service...")
        self._running = True
        logger.info("Peer link service started")
    
    async def stop(self):
        """Stop the peer link service."""
        logger.info("Stopping peer link service...")
        self._running = False
        
        # Close all links
        with self._lock:
            for peer_id, link in self._links.items():
                try:
                    link.close()
                except Exception as e:
                    logger.debug(f"Error closing link to {peer_id}: {e}")
            self._links.clear()
            self._link_info.clear()
        
        logger.info("Peer link service stopped")
    
    def connect_to_peer(self, peer_id: str) -> bool:
        """
        Establish an encrypted link to a peer.
        
        Returns True if link was created, False otherwise.
        """
        if not self._reticulum_service:
            logger.error("Reticulum service not available")
            return False
        
        with self._lock:
            # Check if already connected
            if peer_id in self._links:
                logger.debug(f"Already connected to peer: {peer_id}")
                return True
            
            # Get peer destination from Reticulum service
            peer_dest = self._reticulum_service.get_peer_destination(peer_id)
            if not peer_dest:
                logger.warning(f"Peer destination not found: {peer_id}")
                return False
            
            # Get peer info
            peer = self._reticulum_service.get_peer(peer_id)
            peer_name = peer.name if peer else "Unknown"
            
            # Create link info
            self._link_info[peer_id] = LinkInfo(
                peer_id=peer_id,
                peer_name=peer_name,
                state=LinkState.CONNECTING
            )
            
            try:
                # Create Reticulum link
                link = self._reticulum_service.create_link(peer_id)
                
                if link:
                    # Register callbacks
                    link.register_link_established_callback(
                        self._on_link_established
                    )
                    link.register_link_closed_callback(
                        self._on_link_closed
                    )
                    link.register_packet_callback(
                        self._on_packet_received
                    )
                    
                    self._links[peer_id] = link
                    logger.info(f"Connecting to peer: {peer_name}")
                    return True
                else:
                    logger.error(f"Failed to create link to peer: {peer_id}")
                    self._link_info[peer_id].state = LinkState.ERROR
                    return False
                    
            except Exception as e:
                logger.error(f"Error connecting to peer {peer_id}: {e}")
                if peer_id in self._link_info:
                    self._link_info[peer_id].state = LinkState.ERROR
                return False
    
    def disconnect_from_peer(self, peer_id: str):
        """Close link to a peer."""
        with self._lock:
            if peer_id in self._links:
                try:
                    self._links[peer_id].close()
                except Exception as e:
                    logger.debug(f"Error closing link: {e}")
                
                del self._links[peer_id]
                
                if peer_id in self._link_info:
                    self._link_info[peer_id].state = LinkState.DISCONNECTED
                
                logger.info(f"Disconnected from peer: {peer_id}")
    
    def send_to_peer(self, peer_id: str, data: bytes) -> bool:
        """
        Send data to a peer.
        
        Returns True if sent successfully, False otherwise.
        """
        with self._lock:
            link = self._links.get(peer_id)
            
            if not link:
                logger.warning(f"No link to peer: {peer_id}")
                return False
            
            try:
                link.send(data)
                
                # Update stats
                if peer_id in self._link_info:
                    self._link_info[peer_id].bytes_sent += len(data)
                    self._link_info[peer_id].last_activity = datetime.now()
                
                return True
            except Exception as e:
                logger.error(f"Error sending to peer {peer_id}: {e}")
                return False
    
    def send_text_to_peer(self, peer_id: str, text: str) -> bool:
        """Send text string to a peer."""
        return self.send_to_peer(peer_id, text.encode('utf-8'))
    
    def send_json_to_peer(self, peer_id: str, data: dict) -> bool:
        """Send JSON-serializable data to a peer."""
        import json
        return self.send_to_peer(peer_id, json.dumps(data).encode('utf-8'))
    
    def broadcast(self, data: bytes) -> int:
        """
        Broadcast data to all connected peers.
        
        Returns number of peers sent to.
        """
        count = 0
        with self._lock:
            for peer_id, link in self._links.items():
                try:
                    link.send(data)
                    count += 1
                except Exception as e:
                    logger.debug(f"Error broadcasting to {peer_id}: {e}")
        return count
    
    def register_data_callback(self, peer_id: str, callback: Callable):
        """Register callback for incoming data from a peer."""
        self._data_callbacks[peer_id] = callback
    
    def register_link_callback(self, callback: Callable):
        """Register callback for link state changes."""
        self._link_callbacks.append(callback)
    
    def _on_link_established(self, link):
        """Called when a link is established."""
        # Find peer by link
        with self._lock:
            for peer_id, l in self._links.items():
                if l == link:
                    if peer_id in self._link_info:
                        self._link_info[peer_id].state = LinkState.CONNECTED
                        self._link_info[peer_id].established = datetime.now()
                        self._link_info[peer_id].last_activity = datetime.now()
                    
                    logger.info(f"Link established with peer: {peer_id}")
                    
                    # Notify callbacks
                    for cb in self._link_callbacks:
                        try:
                            cb(peer_id, LinkState.CONNECTED)
                        except Exception as e:
                            logger.error(f"Link callback error: {e}")
                    break
    
    def _on_link_closed(self, link):
        """Called when a link is closed."""
        with self._lock:
            for peer_id, l in self._links.items():
                if l == link:
                    del self._links[peer_id]
                    
                    if peer_id in self._link_info:
                        self._link_info[peer_id].state = LinkState.DISCONNECTED
                    
                    logger.info(f"Link closed with peer: {peer_id}")
                    
                    # Notify callbacks
                    for cb in self._link_callbacks:
                        try:
                            cb(peer_id, LinkState.DISCONNECTED)
                        except Exception as e:
                            logger.error(f"Link callback error: {e}")
                    break
    
    def _on_packet_received(self, packet):
        """Called when data is received."""
        # Get the link that received the packet
        link = packet.link
        
        with self._lock:
            # Find peer by link
            peer_id = None
            for pid, l in self._links.items():
                if l == link:
                    peer_id = pid
                    break
            
            if not peer_id:
                return
            
            # Update stats
            if peer_id in self._link_info:
                self._link_info[peer_id].bytes_received += len(packet.data)
                self._link_info[peer_id].last_activity = datetime.now()
            
            # Get callback
            callback = self._data_callbacks.get(peer_id)
            
            if callback:
                try:
                    callback(peer_id, packet.data)
                except Exception as e:
                    logger.error(f"Data callback error: {e}")
    
    def is_connected_to(self, peer_id: str) -> bool:
        """Check if connected to a specific peer."""
        with self._lock:
            return peer_id in self._links
    
    def get_connected_peers(self) -> list:
        """Get list of peer IDs we're connected to."""
        with self._lock:
            return list(self._links.keys())
    
    def get_link_info(self, peer_id: str) -> Optional[LinkInfo]:
        """Get link information for a peer."""
        with self._lock:
            return self._link_info.get(peer_id)
    
    def get_all_link_info(self) -> Dict[str, LinkInfo]:
        """Get link info for all peers."""
        with self._lock:
            return self._link_info.copy()
