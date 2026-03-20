"""
Transport Layer - Personal Cloud OS

Manages transport selection for peer data:

  FAST   (>1 Mbps)    → WireGuard tunnel (future — requires root)
  MEDIUM (>62.5 Kbps) → RNS.Resource (current default for all links)
  SLOW   (>0)         → RNS.Resource
  OFFLINE             → queue (not yet implemented)

File transfers currently always use RNS.Resource (sync.py handles this
directly). The transport layer provides link classification and bandwidth
tracking. Swarm (torrent-style) is shelved for future multi-peer use.
"""

from transport.detector  import (LinkTier, Transport, LinkProfile,
                                  classify_link, should_warn_transfer)
from transport.bandwidth import BandwidthGovernor
from transport.wireguard import WireGuardManager

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class TransportManager:
    """
    Classifies peer links and tracks bandwidth.
    File transfers are delegated directly to sync.py (RNS.Resource).
    WireGuard tunnel setup is prepared but requires root to activate.
    """

    def __init__(self, peer_link_service, event_bus):
        self._pls       = peer_link_service
        self._event_bus = event_bus
        self.governor   = BandwidthGovernor()
        self.wireguard  = WireGuardManager()
        self._lock      = threading.Lock()

        peer_link_service.register_link_callback(self._on_link_state_changed)
        logger.info("TransportManager initialised")

    def get_transport_for_peer(self, peer_id: str) -> Transport:
        profile = self._pls.get_link_profile(peer_id)
        if profile:
            return profile.transport
        return Transport.RNS

    def get_wireguard_ip(self, peer_id: str) -> Optional[str]:
        return self.wireguard.get_peer_ip(peer_id)

    def get_stats(self) -> dict:
        return self.governor.get_stats()

    def stop(self):
        self.wireguard.tear_down_all()

    def _on_link_state_changed(self, peer_id: str, state):
        from services.peer_link import LinkState
        if state == LinkState.CONNECTED:
            profile = self._pls.get_link_profile(peer_id)
            if profile:
                logger.info(f"Transport: peer connected — {profile.describe()}")
            # WireGuard tunnel setup: only if FAST tier and root available
            if (profile and profile.tier == LinkTier.FAST
                    and self.wireguard.is_available()):
                link = self._pls._links.get(peer_id)
                if link:
                    import threading as _t
                    _t.Thread(
                        target=self._bring_up_wireguard,
                        args=(link, peer_id,
                              profile.peer_name),
                        daemon=True,
                        name=f"wg-up-{peer_id[:8]}",
                    ).start()
        elif state == LinkState.DISCONNECTED:
            self.wireguard.tear_down(peer_id)
            self.governor.remove_peer(peer_id)

    def _bring_up_wireguard(self, link, peer_id: str, peer_name: str):
        tunnel = self.wireguard.bring_up(
            link=link, peer_id=peer_id,
            peer_name=peer_name, initiator=True)
        if tunnel:
            logger.info(
                f"WireGuard ready for {peer_name}: "
                f"{tunnel.local_ip} ↔ {tunnel.peer_ip}")
