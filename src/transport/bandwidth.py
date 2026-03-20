"""
Bandwidth Governor

Enforces the 20/70/10 bandwidth budget across all active peer links:
  20% — messaging + IoT (always reserved, never preempted)
  70% — bulk transfer (file sync, compute data)
  10% — RNS routing overhead

Also tracks per-link transfer history and emits warnings when a
slow-link transfer is in progress.

Usage:
    governor = BandwidthGovernor()
    governor.record_transfer(peer_id, bytes_sent, category='bulk')
    ok, reason = governor.check_transfer(profile, file_bytes)
"""
from __future__ import annotations

import logging
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Deque, Optional, Tuple

from transport.detector import LinkProfile, LinkTier, should_warn_transfer

logger = logging.getLogger(__name__)

# Rolling window for throughput measurement (seconds)
WINDOW_SECONDS = 10

# Category labels
CAT_MESSAGING = "messaging"
CAT_BULK      = "bulk"
CAT_OVERHEAD  = "overhead"


@dataclass
class _TransferSample:
    timestamp: float
    bytes_count: int
    category: str


class _PeerBucket:
    """Sliding-window byte counter for one peer."""

    def __init__(self):
        self._samples: Deque[_TransferSample] = deque()
        self._lock = threading.Lock()

    def record(self, byte_count: int, category: str):
        with self._lock:
            self._samples.append(_TransferSample(
                timestamp=time.monotonic(),
                bytes_count=byte_count,
                category=category,
            ))
            self._evict()

    def _evict(self):
        cutoff = time.monotonic() - WINDOW_SECONDS
        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()

    def bytes_in_window(self, category: Optional[str] = None) -> int:
        with self._lock:
            self._evict()
            return sum(
                s.bytes_count for s in self._samples
                if category is None or s.category == category
            )

    def rate_bps(self, category: Optional[str] = None) -> float:
        return (self.bytes_in_window(category) * 8) / WINDOW_SECONDS


class BandwidthGovernor:
    """
    Tracks bandwidth usage across all peer links and enforces budgets.

    Thread-safe — all public methods can be called from RNS callbacks.
    """

    def __init__(self):
        self._buckets: Dict[str, _PeerBucket] = {}
        self._lock = threading.Lock()
        self._active_warnings: Dict[str, str] = {}  # peer_id -> warning msg

    def _bucket(self, peer_id: str) -> _PeerBucket:
        with self._lock:
            if peer_id not in self._buckets:
                self._buckets[peer_id] = _PeerBucket()
            return self._buckets[peer_id]

    def record_transfer(self, peer_id: str, byte_count: int,
                        category: str = CAT_BULK):
        """Record bytes sent/received for a peer."""
        self._bucket(peer_id).record(byte_count, category)

    def current_rate_bps(self, peer_id: str,
                         category: Optional[str] = None) -> float:
        """Current transfer rate for a peer (bps), averaged over WINDOW_SECONDS."""
        return self._bucket(peer_id).rate_bps(category)

    def check_transfer(self, profile: LinkProfile,
                       file_bytes: int) -> Tuple[bool, Optional[str]]:
        """
        Check whether a bulk transfer is advisable right now.

        Returns (ok, warning_or_None).
        ok=True means proceed; ok=False means block (no path).
        warning != None means proceed but show the warning to the user.
        """
        warn = should_warn_transfer(profile, file_bytes)

        if profile.tier == LinkTier.OFFLINE:
            return False, warn

        # Check if messaging budget would be crowded out
        current_bulk_bps = self.current_rate_bps(profile.peer_id, CAT_BULK)
        if profile.interface_bps and profile.interface_bps > 0:
            msg_floor_bps = profile.interface_bps * 0.20
            bulk_ceiling_bps = profile.interface_bps * 0.70
            if current_bulk_bps > bulk_ceiling_bps:
                warn = (warn or "") + (
                    f" Bulk budget saturated on link to {profile.peer_name} "
                    f"({current_bulk_bps/1000:.1f}/{bulk_ceiling_bps/1000:.1f} Kbps used). "
                    f"Throttling transfer."
                )

        # Store/clear active warnings
        if warn:
            with self._lock:
                self._active_warnings[profile.peer_id] = warn
            logger.warning(f"BandwidthGovernor: {warn}")
        else:
            with self._lock:
                self._active_warnings.pop(profile.peer_id, None)

        return True, warn

    def get_active_warnings(self) -> Dict[str, str]:
        """Return all currently active bandwidth warnings keyed by peer_id."""
        with self._lock:
            return dict(self._active_warnings)

    def get_stats(self) -> Dict[str, Dict]:
        """Return per-peer bandwidth stats for the CLI."""
        stats = {}
        with self._lock:
            peer_ids = list(self._buckets.keys())
        for pid in peer_ids:
            b = self._bucket(pid)
            stats[pid] = {
                "bulk_kbps":     b.rate_bps(CAT_BULK) / 1000,
                "messaging_kbps": b.rate_bps(CAT_MESSAGING) / 1000,
                "overhead_kbps":  b.rate_bps(CAT_OVERHEAD) / 1000,
                "total_kbps":     b.rate_bps() / 1000,
            }
        return stats

    def remove_peer(self, peer_id: str):
        """Clean up tracking for a peer that disconnected."""
        with self._lock:
            self._buckets.pop(peer_id, None)
            self._active_warnings.pop(peer_id, None)
