"""
Transport Layer - Personal Cloud OS

Selects and manages the right data transport for each peer link:

  FAST   (>1 Mbps)      → WireGuard tunnel (RNS-derived keys, full NIC speed)
  MEDIUM (>62.5 Kbps)   → Swarm (torrent-style multi-peer chunking over RNS)
  SLOW   (>0)           → RNS native (RNS.Resource for files, Packet for control)
  OFFLINE               → Queue transfers, RNS messaging only

The transport layer sits between the application (sync, compute) and the
RNS peer link layer.  The application never needs to know which transport
is active — it just calls TransportManager.send_file() or .send_data().

Bandwidth budget (enforced by BandwidthGovernor):
  20% — messaging + IoT  (always reserved)
  70% — bulk transfer
  10% — RNS routing overhead
"""

from transport.detector   import (LinkTier, Transport, LinkProfile,
                                  classify_link, should_warn_transfer)
from transport.bandwidth  import BandwidthGovernor
from transport.wireguard  import WireGuardManager
from transport.swarm      import SwarmManager, file_hash as compute_file_hash

import logging
import os
import threading
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class TransportManager:
    """
    Facade over the transport layer.

    Wired up by main.py after PeerLinkService is running.
    SyncEngine and future compute layers talk to this.
    """

    def __init__(self, peer_link_service, event_bus):
        self._pls       = peer_link_service
        self._event_bus = event_bus

        self.governor   = BandwidthGovernor()
        self.wireguard  = WireGuardManager()
        self.swarm      = SwarmManager(peer_link_service, self.governor)

        self._lock      = threading.Lock()

        # Register for link state changes so we can set up/tear down tunnels
        peer_link_service.register_link_callback(self._on_link_state_changed)

        logger.info("TransportManager initialised")

    # ------------------------------------------------------------------ #
    # High-level API (used by SyncEngine, compute layer, etc.)            #
    # ------------------------------------------------------------------ #

    def send_file(self, peer_id: str, local_path: str,
                  on_complete: Optional[Callable] = None) -> bool:
        """
        Send a file to a peer using the best available transport.

        Returns True if the transfer was initiated, False if not possible.
        A warning is logged (and returned via on_complete err arg) if the
        link is slow.
        """
        if not os.path.exists(local_path):
            logger.error(f"send_file: file not found: {local_path}")
            return False

        profile = self._pls.get_link_profile(peer_id)
        if not profile:
            logger.warning(f"send_file: no link profile for {peer_id[:12]}")
            return False

        file_size = os.path.getsize(local_path)
        ok, warn  = self.governor.check_transfer(profile, file_size)

        if not ok:
            logger.warning(f"send_file blocked: {warn}")
            return False
        if warn:
            logger.warning(warn)

        tier = profile.tier

        if tier == LinkTier.FAST and self.wireguard.is_available():
            # WireGuard is up — transfer happens out-of-band over the tunnel
            # Just notify the peer via control message; actual file copy uses
            # rsync/SCP/NFS over the WireGuard IP (handled by sync.py)
            logger.info(f"send_file: WireGuard path → {profile.peer_name} "
                        f"({file_size/1024:.0f} KB)")
            return True

        elif tier in (LinkTier.MEDIUM,):
            # Swarm transfer
            fh = compute_file_hash(local_path)
            self.swarm.announce(fh, local_path)
            logger.info(f"send_file: swarm path → {profile.peer_name} "
                        f"({file_size/1024:.0f} KB)")
            return True

        else:
            # RNS native — caller (sync.py) handles RNS.Resource directly
            logger.info(f"send_file: RNS native path → {profile.peer_name} "
                        f"({file_size/1024:.0f} KB)")
            return True

    def get_transport_for_peer(self, peer_id: str) -> Transport:
        """Return the current recommended transport for a peer."""
        profile = self._pls.get_link_profile(peer_id)
        if profile:
            return profile.transport
        return Transport.RNS

    def get_wireguard_ip(self, peer_id: str) -> Optional[str]:
        """Return the WireGuard tunnel IP for a peer, or None."""
        return self.wireguard.get_peer_ip(peer_id)

    def get_stats(self) -> dict:
        """Return bandwidth stats for all peers (for CLI display)."""
        return self.governor.get_stats()

    def stop(self):
        """Tear down all tunnels and stop swarm activity."""
        self.wireguard.tear_down_all()
        self.swarm.stop()

    # ------------------------------------------------------------------ #
    # Link state callbacks                                                 #
    # ------------------------------------------------------------------ #

    def _on_link_state_changed(self, peer_id: str, state):
        from services.peer_link import LinkState
        if state == LinkState.CONNECTED:
            self._on_peer_connected(peer_id)
        elif state == LinkState.DISCONNECTED:
            self._on_peer_disconnected(peer_id)

    def _on_peer_connected(self, peer_id: str):
        profile = self._pls.get_link_profile(peer_id)
        if not profile:
            return

        logger.info(f"Transport: peer connected — {profile.describe()}")

        if profile.tier == LinkTier.FAST and self.wireguard.is_available():
            # Spin up WireGuard tunnel in background
            link = self._pls._links.get(peer_id)
            if link:
                threading.Thread(
                    target=self._bring_up_wireguard,
                    args=(link, peer_id, profile.peer_name),
                    daemon=True,
                    name=f"wg-up-{peer_id[:8]}",
                ).start()

    def _on_peer_disconnected(self, peer_id: str):
        self.wireguard.tear_down(peer_id)
        self.governor.remove_peer(peer_id)
        logger.debug(f"Transport: cleaned up peer {peer_id[:12]}")

    def _bring_up_wireguard(self, link, peer_id: str, peer_name: str):
        tunnel = self.wireguard.bring_up(
            link=link,
            peer_id=peer_id,
            peer_name=peer_name,
            initiator=True,   # TODO: determine from RNS link direction
        )
        if tunnel:
            logger.info(
                f"WireGuard tunnel ready for {peer_name}: "
                f"{tunnel.local_ip} ↔ {tunnel.peer_ip}")
