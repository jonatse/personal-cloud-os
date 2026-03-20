"""
=============================================================================
DEPRECATED: Peer Discovery Service (Shelved on 2026-03-19)
=============================================================================

PURPOSE:
    This was a higher-level abstraction layer that sat on top of 
    Reticulum networking. It maintained a separate peer cache and 
    handled peer timeout/expiration.

WHY SHELVED:
    The two-layer architecture (ReticulumPeerService + PeerDiscoveryService)
    created sync issues where peers discovered by Reticulum weren't always
    reflected in the Discovery layer due to event handling race conditions.
    
    The discovery logic is now integrated directly into the Reticulum 
    network service, eliminating the need for a separate layer.

WHAT IT DID:
    - Subscribed to "peer.discovered" events from ReticulumPeerService
    - Converted ReticulumPeer objects to simpler Peer objects
    - Maintained local _peers dict with timeout/expiration logic
    - Published "discovery.peer_found" events

HOW TO REUSE:
    If you need a separate discovery layer in the future, the pattern is:
    1. Subscribe to events from the network service
    2. Convert network-level peer objects to app-level objects
    3. Add business logic (timeouts, filtering, etc.)
    4. Publish higher-level events
    
    Make sure to handle event publish errors carefully to avoid 
    the race conditions that caused issues here.

=============================================================================
"""

"""
Peer Discovery Service - Uses Reticulum ZeroTrust Networking

This replaces the old UDP broadcast discovery with Reticulum-based discovery.
- Uses Reticulum for peer discovery (no UDP broadcast)
- Identity-based: peers with same identity find each other
- Encrypted by default
- Works over any network interface configured in Reticulum
"""
import asyncio
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.events import Event

logger = logging.getLogger(__name__)


@dataclass
class Peer:
    """Represents a discovered peer."""
    id: str
    name: str
    ip: str = ""
    port: int = 0
    last_seen: datetime = None
    status: str = "online"
    metadata: dict = None
    
    def __post_init__(self):
        if self.last_seen is None:
            self.last_seen = datetime.now()
        if self.metadata is None:
            self.metadata = {}
        if isinstance(self.last_seen, str):
            self.last_seen = datetime.fromisoformat(self.last_seen)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "ip": self.ip,
            "port": self.port,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "status": self.status,
            "metadata": self.metadata
        }
    
    def is_expired(self, timeout: int = 60) -> bool:
        """Check if peer has expired."""
        return datetime.now() - self.last_seen > timedelta(seconds=timeout)


class PeerDiscoveryService:
    """
    Peer discovery service using Reticulum ZeroTrust networking.
    
    This replaces the UDP broadcast discovery with Reticulum-based discovery.
    Key benefits:
    - Identity-based: same user identity = automatic discovery
    - Encrypted: all communication is encrypted
    - Works over any network: WiFi, Ethernet, TCP (future), etc.
    - No manual IP/port configuration needed
    """
    
    def __init__(self, config, event_bus):
        """Initialize peer discovery service."""
        self.config = config
        self.event_bus = event_bus
        
        # The Reticulum peer service (will be set by main.py)
        self._reticulum_service = None
        
        # Local peer cache (converted from Reticulum peers)
        self._peers: Dict[str, Peer] = {}
        
        # Configuration
        self._running = False
        self._peer_timeout = config.get("discovery.peer_timeout", 60)
        
        # Subscribe to Reticulum events
        self._setup_event_subscriptions()
        
        logger.info("PeerDiscoveryService initialized (Reticulum-based)")
    
    def _setup_event_subscriptions(self):
        """Subscribe to Reticulum events."""
        self.event_bus.subscribe("peer.discovered", self._on_peer_discovered)
        self.event_bus.subscribe("peer.updated", self._on_peer_updated)
        self.event_bus.subscribe("peer.lost", self._on_peer_lost)
    
    def set_reticulum_service(self, reticulum_service):
        """Set the Reticulum peer service (called from main.py)."""
        self._reticulum_service = reticulum_service
    
    async def _on_peer_discovered(self, event):
        """Handle peer discovered event from Reticulum."""
        try:
            logger.info(f"[DEBUG] _on_peer_discovered called with event: {event}")
            data = event.data
            logger.info(f"[DEBUG] event data: {data}")
            peer = Peer(
                id=data.get("id", ""),
                name=data.get("name", "Unknown"),
                last_seen=datetime.fromisoformat(data.get("last_seen", datetime.now().isoformat())),
                status="online",
                metadata=data.get("metadata", {})
            )
            
            logger.info(f"[DEBUG] Adding peer {peer.id} to _peers dict")
            self._peers[peer.id] = peer
            logger.info(f"[DEBUG] _peers now has {len(self._peers)} items: {list(self._peers.keys())}")
            logger.info(f"Peer discovered: {peer.name}")
            
            # Publish to our event bus
            await self.event_bus.publish(Event(type="discovery.peer_found", data=peer.to_dict(), source="discovery"))
        except Exception as e:
            logger.error(f"[DEBUG] Exception in _on_peer_discovered: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    async def _on_peer_updated(self, event):
        """Handle peer updated event from Reticulum."""
        data = event.data
        peer_id = data.get("id")
        
        if peer_id in self._peers:
            self._peers[peer_id].last_seen = datetime.fromisoformat(
                data.get("last_seen", datetime.now().isoformat())
            )
    
    async def _on_peer_lost(self, event):
        """Handle peer lost event from Reticulum."""
        data = event.data
        peer_id = data.get("id")
        
        if peer_id in self._peers:
            peer = self._peers.pop(peer_id)
            logger.info(f"Peer lost: {peer.name}")
            
            await self.event_bus.publish(
                type="discovery.peer_lost", 
                data={"id": peer_id}, 
                source="discovery"
            )
    
    async def start(self):
        """Start the peer discovery service."""
        if self._running:
            logger.warning("Peer discovery service already running")
            return
        
        logger.info("Starting peer discovery service...")
        self._running = True
        
        # Start the cleanup task
        asyncio.create_task(self._cleanup_loop())
        
        logger.info("Peer discovery service started")
    
    async def stop(self):
        """Stop the peer discovery service."""
        logger.info("Stopping peer discovery service...")
        self._running = False
        self._peers.clear()
        logger.info("Peer discovery service stopped")
    
    async def _cleanup_loop(self):
        """Remove expired peers periodically."""
        while self._running:
            await asyncio.sleep(10)
            self._cleanup_expired_peers()
    
    def _cleanup_expired_peers(self):
        """Remove peers that haven't been seen recently."""
        expired = []
        for peer_id, peer in self._peers.items():
            if peer.is_expired(self._peer_timeout):
                expired.append(peer_id)
        
        for peer_id in expired:
            peer = self._peers.pop(peer_id)
            logger.info(f"Peer expired: {peer.name}")
            asyncio.create_task(self.event_bus.publish(
                type="discovery.peer_lost",
                data={"id": peer_id},
                source="discovery"
            ))
    
    def get_peers(self) -> List[Peer]:
        """Get list of currently discovered peers."""
        logger.info(f"[DEBUG] get_peers called, internal _peers has {len(self._peers)} items: {list(self._peers.keys())}")
        peers = list(self._peers.values())
        
        if self._reticulum_service:
            try:
                ret_peers = self._reticulum_service.get_peers()
                for ret_peer in ret_peers:
                    if ret_peer.id not in self._peers:
                        peer = Peer(
                            id=ret_peer.id,
                            name=ret_peer.name,
                            last_seen=ret_peer.last_seen,
                            status="online",
                            metadata=ret_peer.metadata
                        )
                        self._peers[ret_peer.id] = peer
                peers = list(self._peers.values())
            except Exception as e:
                logger.debug(f"Error getting peers from reticulum: {e}")
        
        return peers
    
    def get_peer(self, peer_id: str) -> Optional[Peer]:
        """Get a specific peer by ID."""
        return self._peers.get(peer_id)
    
    def is_running(self) -> bool:
        """Check if service is running."""
        return self._running
    
    @property
    def peer_count(self) -> int:
        """Get number of discovered peers."""
        return len(self._peers)
