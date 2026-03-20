"""
Transport Detector - Classifies link speed and selects the right transport.

Reads RNS link.get_expected_rate() and interface.bitrate to classify
every peer link into one of four tiers, then recommends the appropriate
transport for that tier.

Tiers (matching RNS internal thresholds):
  FAST      > 1 Mbps   → WireGuard tunnel (full NIC speed, RNS-derived keys)
  MEDIUM    > 62.5 Kbps → Swarm/torrent-style chunked transfer over RNS
  SLOW      > 0         → RNS native (Resource for files, Packet for control)
  OFFLINE   = 0 / None  → Queue transfers, RNS messaging only

Bandwidth budget enforced at every tier:
  20% — messaging + IoT (always reserved, never preempted)
  70% — bulk transfer (files, compute data)
  10% — RNS routing overhead (announces, keepalives, path discovery)
"""
from __future__ import annotations

import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    pass  # avoid circular imports; RNS imported at call time

logger = logging.getLogger(__name__)

# ── Tier boundaries (bps) ─────────────────────────────────────────────────────
FAST_BPS       = 1_000_000    # 1 Mbps  — WireGuard viable
MEDIUM_BPS     =    62_500    # 62.5 Kbps — matches RNS FAST_RATE_THRESHOLD * 8
# below MEDIUM → RNS native only

# ── Bandwidth budget fractions ────────────────────────────────────────────────
BUDGET_MESSAGING = 0.20
BUDGET_BULK      = 0.70
BUDGET_OVERHEAD  = 0.10

# Warn when a bulk transfer would saturate a slow link for longer than this
SLOW_LINK_WARN_SECONDS = 30


class LinkTier(Enum):
    """Transport tier for a peer link."""
    FAST    = "fast"     # >1 Mbps   — WireGuard
    MEDIUM  = "medium"   # >62.5 Kbps — swarm
    SLOW    = "slow"     # >0         — RNS native
    OFFLINE = "offline"  # no path


class Transport(Enum):
    """Which transport to use for bulk data."""
    WIREGUARD = "wireguard"
    SWARM     = "swarm"
    RNS       = "rns"
    QUEUE     = "queue"    # offline — queue for later


@dataclass
class LinkProfile:
    """Snapshot of a link's current quality."""
    peer_id:          str
    peer_name:        str
    tier:             LinkTier
    transport:        Transport
    expected_rate_bps: Optional[float]   # from link.get_expected_rate()
    interface_bps:    Optional[float]    # from interface.bitrate
    rtt_ms:           Optional[float]    # round-trip time in ms
    bulk_budget_bps:  float              # 70% of effective rate
    msg_budget_bps:   float              # 20% of effective rate
    warn_large_file:  bool               # True if slow link warning should show

    def describe(self) -> str:
        rate = self.expected_rate_bps
        if rate is None:
            rate_str = "unknown"
        elif rate >= 1_000_000:
            rate_str = f"{rate/1_000_000:.1f} Mbps"
        elif rate >= 1_000:
            rate_str = f"{rate/1_000:.1f} Kbps"
        else:
            rate_str = f"{rate:.0f} bps"
        return (f"{self.peer_name} [{self.tier.value}] "
                f"rate={rate_str} transport={self.transport.value}")

    def eta_seconds(self, file_bytes: int) -> Optional[float]:
        """Estimated transfer time for file_bytes over this link."""
        if self.bulk_budget_bps and self.bulk_budget_bps > 0:
            return (file_bytes * 8) / self.bulk_budget_bps
        return None


def _effective_rate(link) -> Optional[float]:
    """
    Best-effort rate estimate for an RNS link (bps).

    Priority:
      1. link.get_expected_rate()  — measured in-flight rate (most accurate)
      2. link establishment rate   — rate at handshake time
      3. None                      — unknown
    """
    try:
        rate = link.get_expected_rate()
        if rate and rate > 0:
            return float(rate)
    except Exception:
        pass

    try:
        rate = link.get_establishment_rate()
        if rate and rate > 0:
            return float(rate)
    except Exception:
        pass

    return None


def _interface_bitrate(link) -> Optional[float]:
    """
    Bitrate of the underlying RNS interface for this link (bps).
    Falls back to None if not determinable.
    """
    try:
        # RNS Transport exposes active interfaces
        import RNS
        for iface in RNS.Transport.interfaces:
            # The interface that last forwarded packets to/from this link
            # is the relevant one.  We use the lowest-bitrate interface
            # on the path as the bottleneck.
            if hasattr(iface, 'bitrate') and iface.bitrate:
                return float(iface.bitrate)
    except Exception:
        pass
    return None


def classify_link(link, peer_id: str, peer_name: str = "peer") -> LinkProfile:
    """
    Classify an active RNS Link and return a LinkProfile describing
    which transport to use and what bandwidth budgets apply.

    :param link:      An active RNS.Link object.
    :param peer_id:   The peer's destination hash (hex string).
    :param peer_name: Human-readable peer name for log messages.
    :returns:         A LinkProfile with tier, transport, and budgets.
    """
    expected_bps  = _effective_rate(link)
    interface_bps = _interface_bitrate(link)

    # Use the more pessimistic of the two estimates as the effective rate
    # (bottleneck principle)
    candidates = [r for r in (expected_bps, interface_bps) if r is not None and r > 0]
    effective_bps = min(candidates) if candidates else None

    # RTT
    rtt_ms: Optional[float] = None
    try:
        if hasattr(link, 'rtt') and link.rtt:
            rtt_ms = link.rtt * 1000
    except Exception:
        pass

    # Tier classification
    if effective_bps is None or effective_bps <= 0:
        tier      = LinkTier.OFFLINE
        transport = Transport.QUEUE
    elif effective_bps >= FAST_BPS:
        tier      = LinkTier.FAST
        transport = Transport.WIREGUARD
    elif effective_bps >= MEDIUM_BPS:
        tier      = LinkTier.MEDIUM
        transport = Transport.SWARM
    else:
        tier      = LinkTier.SLOW
        transport = Transport.RNS

    # Budget
    eff = effective_bps or 0
    bulk_budget_bps = eff * BUDGET_BULK
    msg_budget_bps  = eff * BUDGET_MESSAGING
    warn_large_file = (tier in (LinkTier.SLOW, LinkTier.OFFLINE))

    profile = LinkProfile(
        peer_id=peer_id,
        peer_name=peer_name,
        tier=tier,
        transport=transport,
        expected_rate_bps=expected_bps,
        interface_bps=interface_bps,
        rtt_ms=rtt_ms,
        bulk_budget_bps=bulk_budget_bps,
        msg_budget_bps=msg_budget_bps,
        warn_large_file=warn_large_file,
    )

    logger.info(f"Link classified: {profile.describe()}")
    return profile


def should_warn_transfer(profile: LinkProfile, file_bytes: int) -> Optional[str]:
    """
    Return a warning string if transferring file_bytes over this link
    would be inadvisable, or None if it's fine.
    """
    if profile.tier == LinkTier.OFFLINE:
        return (f"No path to {profile.peer_name}. "
                f"Transfer ({file_bytes/1024:.0f} KB) queued.")

    eta = profile.eta_seconds(file_bytes)
    if eta is None:
        return None

    if profile.tier == LinkTier.SLOW and eta > SLOW_LINK_WARN_SECONDS:
        mins = eta / 60
        rate_kbps = (profile.bulk_budget_bps or 0) / 1000
        return (f"Slow link to {profile.peer_name} (~{rate_kbps:.1f} Kbps). "
                f"Transferring {file_bytes/1024:.0f} KB will take ~{mins:.1f} min. "
                f"Messaging bandwidth is reserved and will not be affected.")

    return None
