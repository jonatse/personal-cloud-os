"""
WireGuard Transport - Fast encrypted tunnels keyed from RNS shared secrets.

Flow:
  1. RNS Link is established → X25519 key exchange done, derived_key available
  2. derive_wg_keys(link) extracts both peers' WireGuard key material from
     the RNS-negotiated shared secret (HKDF expansion — no new crypto needed)
  3. A point-to-point WireGuard interface is spun up: wg-pcos-<peer_id[:8]>
  4. Peer assigns itself an address from a deterministic /30 from the link hash
  5. All bulk data (sync, compute) uses the WireGuard IP — full NIC speed
  6. The tunnel is torn down when the RNS link closes

Requirements (checked at runtime, not at import):
  - Linux kernel ≥ 5.6 (wireguard module built-in) or wireguard-tools installed
  - Root or CAP_NET_ADMIN capability for interface management
  - 'ip' and 'wg' commands on PATH

If WireGuard is unavailable the tunnel manager silently falls back to
reporting Transport.SWARM or Transport.RNS — the rest of the stack adapts.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import shutil
import struct
import subprocess
import threading
from base64 import b64encode, b64decode
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# WireGuard interface name prefix (max 15 chars total for Linux)
_IFACE_PREFIX = "wgpcos"

# Private /24 used for all tunnel addresses: 10.pcos.0.0/16 → 10.200.x.x
# Each peer pair gets a deterministic /30 from this space.
_TUNNEL_BASE = ipaddress.IPv4Network("10.200.0.0/16")

# UDP port range for WireGuard listen ports (ephemeral, per-peer)
_WG_PORT_BASE = 51820
_WG_PORT_RANGE = 1000


@dataclass
class WireGuardTunnel:
    """Represents one active WireGuard tunnel to a peer."""
    peer_id:      str
    peer_name:    str
    iface:        str          # e.g. "wgpcos1a2b3c4d"
    local_ip:     str          # our IP inside the tunnel  e.g. "10.200.1.1"
    peer_ip:      str          # peer IP inside the tunnel e.g. "10.200.1.2"
    listen_port:  int
    local_privkey_b64:  str    # our WireGuard private key (base64)
    peer_pubkey_b64:    str    # peer's WireGuard public key (base64)
    active:       bool = False


class WireGuardManager:
    """
    Manages ephemeral WireGuard tunnels keyed from RNS link secrets.

    Thread-safe — tunnel setup/teardown runs in worker threads.
    """

    def __init__(self):
        self._tunnels: Dict[str, WireGuardTunnel] = {}
        self._lock    = threading.Lock()
        self._available: Optional[bool] = None   # cached capability check

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def is_available(self) -> bool:
        """Return True if WireGuard can be used on this machine."""
        if self._available is not None:
            return self._available
        self._available = self._check_availability()
        return self._available

    def bring_up(self, link, peer_id: str, peer_name: str,
                 initiator: bool) -> Optional[WireGuardTunnel]:
        """
        Derive WireGuard keys from the RNS link secret and bring up a tunnel.

        :param link:      Active RNS.Link object.
        :param peer_id:   Peer's destination hash (hex string).
        :param peer_name: Human-readable peer name.
        :param initiator: True if we initiated the RNS link (we pick .1, peer gets .2).
        :returns:         WireGuardTunnel on success, None on failure.
        """
        if not self.is_available():
            logger.info("WireGuard not available — skipping tunnel setup")
            return None

        with self._lock:
            if peer_id in self._tunnels and self._tunnels[peer_id].active:
                return self._tunnels[peer_id]

        try:
            tunnel = self._setup_tunnel(link, peer_id, peer_name, initiator)
            with self._lock:
                self._tunnels[peer_id] = tunnel
            logger.info(
                f"WireGuard tunnel up: {tunnel.iface} "
                f"{tunnel.local_ip} ↔ {tunnel.peer_ip}"
            )
            return tunnel
        except Exception as exc:
            logger.error(f"WireGuard bring_up failed for {peer_name}: {exc}",
                         exc_info=True)
            return None

    def tear_down(self, peer_id: str):
        """Tear down the WireGuard tunnel for peer_id."""
        with self._lock:
            tunnel = self._tunnels.pop(peer_id, None)
        if tunnel and tunnel.active:
            self._remove_interface(tunnel.iface)
            logger.info(f"WireGuard tunnel removed: {tunnel.iface}")

    def tear_down_all(self):
        """Tear down all active tunnels (called on app shutdown)."""
        with self._lock:
            tunnels = list(self._tunnels.values())
            self._tunnels.clear()
        for tunnel in tunnels:
            if tunnel.active:
                self._remove_interface(tunnel.iface)

    def get_tunnel(self, peer_id: str) -> Optional[WireGuardTunnel]:
        with self._lock:
            return self._tunnels.get(peer_id)

    def get_peer_ip(self, peer_id: str) -> Optional[str]:
        """Return the WireGuard tunnel IP for a peer, or None if no tunnel."""
        with self._lock:
            t = self._tunnels.get(peer_id)
            return t.peer_ip if t and t.active else None

    # ------------------------------------------------------------------ #
    # Key derivation                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def derive_wg_keys(link, peer_id: str, initiator: bool):
        """
        Derive deterministic WireGuard key material from the RNS link secret.

        Both peers perform the same HKDF expansion on the shared derived_key,
        then use different halves so each gets a unique private key without
        any additional round-trip.

        Returns (local_privkey_bytes, peer_pubkey_bytes).
        """
        import RNS

        # Get the shared secret from the RNS link handshake
        derived_key: Optional[bytes] = getattr(link, 'derived_key', None)
        if not derived_key:
            raise ValueError("Link has no derived_key — is it ACTIVE?")

        # Expand to 64 bytes: first 32 = our privkey material, next 32 = peer's
        salt    = peer_id.encode()[:32].ljust(32, b'\x00')
        context = b"pcos-wireguard-v1"
        expanded = RNS.Cryptography.hkdf(
            length=64,
            derive_from=derived_key,
            salt=salt,
            context=context,
        )

        # Initiator uses bytes 0-31, responder uses bytes 32-63
        # This ensures each side derives a *different* private key from the
        # same shared secret, which is required for WireGuard (peer keys must differ)
        if initiator:
            local_priv_raw  = expanded[:32]
            remote_priv_raw = expanded[32:]
        else:
            local_priv_raw  = expanded[32:]
            remote_priv_raw = expanded[:32]

        # Clamp for Curve25519 (WireGuard requirement)
        local_priv  = _clamp_curve25519(local_priv_raw)
        remote_priv = _clamp_curve25519(remote_priv_raw)

        # Derive the public key from the remote private key so we know what
        # to configure as the peer's allowed public key
        remote_pub = _curve25519_public_key(remote_priv)

        return local_priv, remote_pub

    # ------------------------------------------------------------------ #
    # Internal tunnel management                                           #
    # ------------------------------------------------------------------ #

    def _setup_tunnel(self, link, peer_id: str, peer_name: str,
                      initiator: bool) -> WireGuardTunnel:
        """Derive keys, configure interface, bring it up."""
        local_priv_bytes, peer_pub_bytes = self.derive_wg_keys(
            link, peer_id, initiator)

        local_priv_b64 = b64encode(local_priv_bytes).decode()
        peer_pub_b64   = b64encode(peer_pub_bytes).decode()

        # Deterministic tunnel address from the peer_id hash
        local_ip, peer_ip = _tunnel_addresses(peer_id, initiator)

        # Interface name: wgpcos + first 8 chars of peer_id
        iface = f"{_IFACE_PREFIX}{peer_id[:8]}"

        # Pick a listen port deterministically from peer_id so both sides
        # agree (though for a point-to-point tunnel only the responder needs it)
        port_seed = int.from_bytes(bytes.fromhex(peer_id[:8]), "big")
        listen_port = _WG_PORT_BASE + (port_seed % _WG_PORT_RANGE)

        # Tear down any existing interface with this name
        self._remove_interface(iface)

        # Create and configure the interface
        self._create_interface(iface)
        self._configure_wg(
            iface=iface,
            local_priv_b64=local_priv_b64,
            peer_pub_b64=peer_pub_b64,
            local_ip=local_ip,
            listen_port=listen_port,
        )
        self._bring_up(iface)

        tunnel = WireGuardTunnel(
            peer_id=peer_id,
            peer_name=peer_name,
            iface=iface,
            local_ip=local_ip,
            peer_ip=peer_ip,
            listen_port=listen_port,
            local_privkey_b64=local_priv_b64,
            peer_pubkey_b64=peer_pub_b64,
            active=True,
        )
        return tunnel

    def _create_interface(self, iface: str):
        _run(["ip", "link", "add", "dev", iface, "type", "wireguard"])

    def _configure_wg(self, iface: str, local_priv_b64: str,
                      peer_pub_b64: str, local_ip: str, listen_port: int):
        # Set private key
        _run(["wg", "set", iface,
              "listen-port", str(listen_port),
              "private-key", "/dev/stdin"],
             input_data=local_priv_b64.encode())
        # Add peer (allow all tunnel traffic)
        _run(["wg", "set", iface,
              "peer", peer_pub_b64,
              "allowed-ips", "0.0.0.0/0"])
        # Assign IP
        _run(["ip", "address", "add", f"{local_ip}/30", "dev", iface])

    def _bring_up(self, iface: str):
        _run(["ip", "link", "set", "up", "dev", iface])

    def _remove_interface(self, iface: str):
        try:
            _run(["ip", "link", "del", iface])
        except Exception:
            pass  # interface may not exist

    def _check_availability(self) -> bool:
        if os.geteuid() != 0:
            logger.info(
                "WireGuard not available: not running as root "
                "(CAP_NET_ADMIN required for interface management)")
            return False
        if not shutil.which("wg"):
            logger.info("WireGuard not available: 'wg' command not found")
            return False
        if not shutil.which("ip"):
            logger.info("WireGuard not available: 'ip' command not found")
            return False
        # Check kernel module
        try:
            result = _run(["ip", "link", "add", "wgpcos_test", "type", "wireguard"],
                          check=False)
            _run(["ip", "link", "del", "wgpcos_test"], check=False)
            return True
        except Exception:
            return False


# ── Helpers ──────────────────────────────────────────────────────────────── #

def _run(cmd: list, input_data: bytes = None, check: bool = True):
    result = subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        check=check,
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"Command {cmd[0]} failed: {result.stderr.decode().strip()}")
    return result


def _clamp_curve25519(key_bytes: bytes) -> bytes:
    """Apply RFC 7748 clamping to a 32-byte Curve25519 private key."""
    k = bytearray(key_bytes)
    k[0]  &= 248
    k[31] &= 127
    k[31] |= 64
    return bytes(k)


def _curve25519_public_key(priv_bytes: bytes) -> bytes:
    """
    Derive the Curve25519 public key from a private key.
    Uses the cryptography library (available in src/vendor/).
    """
    try:
        from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
        priv = X25519PrivateKey.from_private_bytes(priv_bytes)
        pub  = priv.public_key()
        return pub.public_bytes_raw()
    except Exception as exc:
        raise RuntimeError(f"Curve25519 public key derivation failed: {exc}") from exc


def _tunnel_addresses(peer_id: str, initiator: bool):
    """
    Derive a deterministic /30 tunnel address pair from the peer_id hash.

    Returns (local_ip, peer_ip) as strings.
    The initiator takes .1, the responder takes .2 in the /30.
    """
    # Hash peer_id to get a /30 offset within 10.200.0.0/16
    # There are 16384 possible /30 subnets in a /16 (65536 / 4)
    h = int(hashlib.sha256(peer_id.encode()).hexdigest(), 16)
    subnet_index = h % 16384
    # Each /30 is 4 addresses; base of the /30 is subnet_index * 4
    base_int = int(_TUNNEL_BASE.network_address) + subnet_index * 4

    if initiator:
        local_int = base_int + 1
        peer_int  = base_int + 2
    else:
        local_int = base_int + 2
        peer_int  = base_int + 1

    return str(ipaddress.IPv4Address(local_int)), str(ipaddress.IPv4Address(peer_int))
