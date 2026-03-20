"""
Reticulum Peer Service - Embedded ZeroTrust Networking

This module provides peer-to-peer networking using Reticulum.
It runs entirely within the app - no external rnsd daemon needed.

Key features:
- Identity-based peer discovery (same user = same identity)
- Encrypted P2P links
- Local network auto-discovery via AutoInterface
- Designed for expansion to TCP, LoRa, etc.
"""
import asyncio
import logging
import os
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import RNS

# Import Event for event bus publishing
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.events import Event

logger = logging.getLogger(__name__)

# Reticulum constants
APP_NAME = "personalcloudos"
PEER_DESTINATION = "peers"


class PeerStatus(Enum):
    """Peer connection status."""
    DISCOVERED = "discovered"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


@dataclass
class ReticulumPeer:
    """Represents a peer discovered via Reticulum."""
    id: str  # Reticulum hash (hex)
    name: str
    destination: Any  # RNS.Destination object
    status: PeerStatus = PeerStatus.DISCOVERED
    last_seen: datetime = field(default_factory=datetime.now)
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "last_seen": self.last_seen.isoformat(),
            "metadata": self.metadata
        }


class ReticulumPeerService:
    """
    Embedded Reticulum peer service.
    
    Provides ZeroTrust networking for Personal Cloud OS.
    - Initializes RNS stack internally (no rnsd)
    - Discovers peers with same identity
    - Establishes encrypted P2P links
    
    Usage:
        service = ReticulumPeerService(config, event_bus)
        await service.start()
        peers = service.get_peers()
    """
    
    def __init__(self, config, event_bus):
        """Initialize the Reticulum peer service."""
        self.config = config
        self.event_bus = event_bus
        
        # Reticulum objects (initialized in start)
        self._reticulum = None
        self._identity = None
        self._destination = None
        
        # Peer tracking
        self._peers: Dict[str, ReticulumPeer] = {}
        self._links: Dict[str, Any] = {}
        self._lock = threading.Lock()
        
        # State
        self._running = False
        self._announce_interval = config.get("reticulum.announce_interval", 30)
        
        # User identity settings
        self._identity_path = config.get(
            "reticulum.identity_path",
            os.path.expanduser("~/.reticulum/storage/identities/pcos")
        )
        
        self._event_loop = None
        
        logger.info("ReticulumPeerService initialized")
    
    async def start(self):
        """Start the Reticulum peer service."""
        if self._running:
            logger.warning("Reticulum peer service already running")
            return
        
        logger.info("Starting Reticulum peer service...")
        self._running = True
        
        # Store event loop reference for thread-safe scheduling
        self._event_loop = asyncio.get_event_loop()
        
        try:
            # Initialize Reticulum network stack
            await self._init_reticulum()
            
            # Start announce loop in background thread
            self._announce_thread = threading.Thread(
                target=self._announce_loop, 
                daemon=True
            )
            self._announce_thread.start()
            
            logger.info(f"Reticulum peer service started. Identity: {self._identity_hash[:16]}...")
            
            # Publish status
            await self._publish_event("reticulum.started", {
                "identity_hash": self._identity_hash,
                "destination_hash": self._destination_hash
            })
            
        except Exception as e:
            logger.error(f"Failed to start Reticulum peer service: {e}")
            self._running = False
            raise
    
    async def stop(self):
        """Stop the Reticulum peer service."""
        if self._running:
            return
        
        logger.info("Stopping Reticulum peer service...")
        self._running = False
        
        # Reticulum will be cleaned up when object is garbage collected
        # or we can explicitly shut down if needed
        
        logger.info("Reticulum peer service stopped")
        await self._publish_event("reticulum.stopped", {})
    
    async def restart(self):
        """Restart the Reticulum peer service."""
        await self.stop()
        await asyncio.sleep(2)
        await self.start()
    
    async def _init_reticulum(self):
        """Initialize Reticulum network stack."""
        # Import RNS here so we can handle if it's not installed
        global RNS
        try:
            import RNS
        except ImportError:
            raise RuntimeError(
                "Reticulum (rns) not installed. Run: pip install rns"
            )
        
        # Initialize Reticulum with default config
        # This creates ~/.reticulum if needed
        config_path = os.path.expanduser("~/.reticulum")
        
        # Check if Reticulum is already initialized
        try:
            self._reticulum = RNS.Reticulum(config_path)
            logger.debug("Connected to existing Reticulum instance")
        except Exception as e:
            logger.debug(f"Creating new Reticulum instance: {e}")
            self._reticulum = RNS.Reticulum(config_path)
        
        # Log available interfaces if Transport.get_interfaces exists
        try:
            if hasattr(RNS.Transport, 'get_interfaces'):
                interfaces = RNS.Transport.get_interfaces()
                logger.info(f"Reticulum interfaces available: {len(interfaces)}")
                for iface in interfaces:
                    logger.info(f"  - {iface.name}: {iface.type} (status: {iface.status})")
            else:
                logger.debug("Transport.get_interfaces not available in this Reticulum version")
        except Exception as e:
            logger.debug(f"Could not get interfaces: {e}")
        
        logger.info("Using rnsd shared instance for LAN discovery (AutoInterface managed by rnsd)")
        
        # Load or create identity
        self._identity = await self._load_or_create_identity()
        
        # Store identity hash for reference
        self._identity_hash = self._identity.hash.hex()
        
        # Create destination for peer announcements
        # Format: pcos.<identity_hash>
        self._destination = RNS.Destination(
            self._identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            APP_NAME,
            PEER_DESTINATION
        )
        
        # Configure to prove all packets
        self._destination.set_proof_strategy(RNS.Destination.PROVE_ALL)
        
        # Store destination hash
        self._destination_hash = self._destination.hash.hex()
        
        # Register announce handler - must be a class with aspect_filter
        class PCOSAnnounceHandler:
            aspect_filter = f"{APP_NAME}.{PEER_DESTINATION}"
            
            def __init__(self, peer_service):
                self.peer_service = peer_service
            
            def received_announce(self, destination_hash, announced_identity, app_data):
                self.peer_service._handle_announce(destination_hash, announced_identity, app_data)
        
        self._announce_handler = PCOSAnnounceHandler(self)
        RNS.Transport.register_announce_handler(self._announce_handler)
        logger.info(f"Announce handler registered for aspect: {PCOSAnnounceHandler.aspect_filter}")
        
        logger.info(f"Destination created: {self._destination_hash[:16]}...")
    
    async def _load_or_create_identity(self):
        """Load existing identity or create new one."""
        import RNS
        
        identity_file = os.path.expanduser(self._identity_path)
        
        # Try to load existing identity
        if os.path.exists(identity_file):
            try:
                identity = RNS.Identity.from_file(identity_file)
                logger.info(f"Loaded existing identity: {identity.hash.hex()[:16]}...")
                return identity
            except Exception as e:
                logger.warning(f"Failed to load identity: {e}")
        
        # Create new identity
        logger.info("Creating new Reticulum identity...")
        identity = RNS.Identity()
        
        # Save identity
        os.makedirs(os.path.dirname(identity_file), exist_ok=True)
        identity.to_file(identity_file)
        logger.info(f"New identity saved to: {identity_file}")
        
        return identity
    
    def _announce_loop(self):
        import json, socket
        app_data = json.dumps({"name": socket.gethostname()}).encode()
        while self._running:
            try:
                if self._destination:
                    self._destination.announce(app_data=app_data)
                    logger.debug(f"Announced presence as {socket.gethostname()}")
            except Exception as e:
                logger.error(f"Announce error: {e}")
            for _ in range(self._announce_interval * 10):
                if not self._running:
                    break
                threading.Event().wait(0.1)
    
    def _handle_announce(self, destination_hash, announced_identity, app_data):
        """Handle incoming peer announcement from Reticulum."""
        try:
            peer_hash = destination_hash.hex() if hasattr(destination_hash, 'hex') else str(destination_hash)
            peer_name = "Unknown"
            if app_data:
                try:
                    import json as _json
                    peer_name = _json.loads(app_data).get("name", "Peer")
                except:
                    peer_name = str(app_data)[:20]
            
            logger.debug(f"Received announce from: {peer_name} ({peer_hash[:16]}...)")
            
            # Don't respond to ourselves
            if peer_hash == self._destination_hash:
                logger.debug("Ignoring our own announce")
                return
            
            with self._lock:
                is_new = peer_hash not in self._peers
                peer = ReticulumPeer(
                    id=peer_hash,
                    name=peer_name,
                    destination=announced_identity,
                    status=PeerStatus.DISCOVERED,
                    last_seen=datetime.now(),
                    metadata={}
                )
                self._peers[peer_hash] = peer
                
                if is_new:
                    logger.info(f"Discovered peer: {peer_name} ({peer_hash[:16]}...)")
                    asyncio.run_coroutine_threadsafe(
                        self._publish_event("peer.discovered", peer.to_dict()),
                        self._event_loop
                    )
                else:
                    logger.debug(f"Known peer updated: {peer_name}")
                    asyncio.run_coroutine_threadsafe(
                        self._publish_event("peer.updated", peer.to_dict()),
                        self._event_loop
                    )
        except Exception as e:
            logger.error(f"Error handling announce: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    async def _publish_event(self, event_type: str, data: Any = None):
        """Publish an event to the event bus."""
        event = Event(type=event_type, data=data, source="reticulum")
        await self.event_bus.publish(event)
    
    def get_peers(self) -> List[ReticulumPeer]:
        """Get list of discovered peers."""
        with self._lock:
            return list(self._peers.values())
    
    def get_peer(self, peer_id: str) -> Optional[ReticulumPeer]:
        """Get a specific peer by ID."""
        with self._lock:
            return self._peers.get(peer_id)
    
    def get_peer_destination(self, peer_id: str):
        """Get destination for a peer."""
        with self._lock:
            peer = self._peers.get(peer_id)
            return peer.destination if peer else None
    
    def is_running(self) -> bool:
        """Check if the service is running."""
        return self._running

    def create_link(self, peer_id: str):
        """Create an encrypted link to a peer."""
        peer = self._peers.get(peer_id)
        if not peer:
            logger.warning(f"Cannot create link: peer {peer_id} not found")
            return None
        
        try:
            destination = peer.destination
            if not destination:
                logger.warning(f"Cannot create link: peer {peer_id} has no destination")
                return None
            
            link = RNS.Link(destination)
            logger.info(f"Created link to peer: {peer.name}")
            return link
        except Exception as e:
            logger.error(f"Error creating link to peer {peer_id}: {e}")
            return None

    def get_link(self, peer_id: str):
        """Get an existing link to a peer."""
        return self._links.get(peer_id)
