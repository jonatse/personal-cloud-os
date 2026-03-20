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
    File transfers go directly through sync.py (RNS.Resource).
    WireGuard tunnel setup is available when root/CAP_NET_ADMIN is present.
    """

    def __init__(self, reticulum_service, event_bus):
        self._rns       = reticulum_service
        self._event_bus = event_bus
        self.governor   = BandwidthGovernor()
        self.wireguard  = WireGuardManager()

        logger.info("TransportManager initialised")

    def get_stats(self) -> dict:
        return self.governor.get_stats()

    def stop(self):
        self.wireguard.tear_down_all()
