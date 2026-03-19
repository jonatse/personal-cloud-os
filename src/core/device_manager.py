"""
Device Manager - Device fingerprinting, identity, and inventory management

Handles:
- Uniquely identifying this device by hostname + MAC address
- Per-device Reticulum identity (never shared between devices)
- Device self-registration in inventory
- Hardware detection and inventory updates
"""
import os
import json
import socket
import uuid
import hashlib
import logging
import platform
import subprocess
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

INVENTORY_PATH = os.path.join(os.path.dirname(__file__), "device_inventory.json")


class DeviceManager:
    """
    Manages device identity, fingerprinting, and the device inventory.
    
    On startup:
    1. Fingerprints this device (hostname + MAC)
    2. Derives a stable device_id from that fingerprint
    3. Looks up self in device_inventory.json
    4. Adds self to inventory if not found
    5. Updates hardware info if anything changed
    6. Provides a device-specific Reticulum identity path so each
       device gets its own cryptographic identity
    """

    def __init__(self):
        self.hostname = socket.gethostname()
        self.mac = self._get_mac()
        self.device_id = self._derive_device_id()
        self.identity_path = self._get_identity_path()
        self.inventory = self._load_inventory()
        logger.info(f"DeviceManager: hostname={self.hostname}, mac={self.mac}, device_id={self.device_id}")
        logger.info(f"DeviceManager: identity_path={self.identity_path}")

    # ------------------------------------------------------------------ #
    #  Fingerprinting                                                       #
    # ------------------------------------------------------------------ #

    def _get_mac(self) -> str:
        """Get MAC address as a clean hex string (e.g. 60452ede5053)."""
        mac_int = uuid.getnode()
        mac_hex = f"{mac_int:012x}"
        logger.debug(f"MAC address: {mac_hex}")
        return mac_hex

    def _derive_device_id(self) -> str:
        """
        Derive a stable, unique device_id from hostname + MAC.
        Returns a short 16-char hex string.
        Never changes as long as the hardware and hostname stay the same.
        """
        fingerprint = f"{self.hostname}:{self.mac}".encode()
        device_id = hashlib.sha256(fingerprint).hexdigest()[:16]
        logger.debug(f"Device fingerprint: {self.hostname}:{self.mac} -> {device_id}")
        return device_id

    def _get_identity_path(self) -> str:
        """
        Return a device-specific Reticulum identity path.
        Uses last 6 chars of MAC so it's human-readable but unique.
        e.g. ~/.reticulum/storage/identities/pcos_e5053
        """
        suffix = self.mac[-6:]
        path = os.path.expanduser(f"~/.reticulum/storage/identities/pcos_{suffix}")
        logger.info(f"Device-specific identity path: {path}")
        return path

    # ------------------------------------------------------------------ #
    #  Inventory                                                            #
    # ------------------------------------------------------------------ #

    def _load_inventory(self) -> dict:
        """Load device_inventory.json, return empty structure if missing."""
        if os.path.exists(INVENTORY_PATH):
            try:
                with open(INVENTORY_PATH, "r") as f:
                    data = json.load(f)
                logger.info(f"Loaded device inventory: {len(data.get('devices', {}))} devices")
                return data
            except Exception as e:
                logger.error(f"Failed to load inventory: {e}")
        logger.warning("No device inventory found, starting fresh")
        return {"devices": {}}

    def _save_inventory(self):
        """Save current inventory back to JSON."""
        try:
            with open(INVENTORY_PATH, "w") as f:
                json.dump(self.inventory, f, indent=2)
            logger.debug("Device inventory saved")
        except Exception as e:
            logger.error(f"Failed to save inventory: {e}")

    def register_self(self):
        """
        Find this device in inventory by device_id.
        If not found, add it. If found, update hardware info.
        Logs exactly what it's doing at each step.
        """
        devices = self.inventory.setdefault("devices", {})

        # First: try to find by device_id
        existing_key = None
        for key, dev in devices.items():
            if dev.get("device_id") == self.device_id:
                existing_key = key
                logger.info(f"Found self in inventory as '{key}' (device_id match)")
                break

        # Second: try to find by hostname (legacy entries without device_id)
        if existing_key is None:
            for key, dev in devices.items():
                if dev.get("hostname") == self.hostname and "device_id" not in dev:
                    existing_key = key
                    logger.info(f"Found self in inventory as '{key}' (hostname match, upgrading)")
                    break

        if existing_key is None:
            # New device - add to inventory
            logger.info(f"Device not found in inventory, registering as new device: {self.hostname}")
            existing_key = self.hostname
            devices[existing_key] = {
                "name": self.hostname,
                "hostname": self.hostname,
                "device_id": self.device_id,
                "mac": self.mac,
                "is_local": True,
                "ssh": None,
                "project_path": str(Path(__file__).parent.parent.parent),
                "identity_path": self.identity_path,
                "hardware": {},
                "network": {},
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
        else:
            # Existing device - ensure device_id and mac are set
            device = devices[existing_key]
            if "device_id" not in device:
                logger.info(f"Upgrading inventory entry '{existing_key}' with device_id")
            device["device_id"] = self.device_id
            device["mac"] = self.mac
            device["hostname"] = self.hostname
            device["identity_path"] = self.identity_path
            device["is_local"] = True

        # Always update hardware and network
        self._update_hardware(devices[existing_key])
        self._update_network(devices[existing_key])
        devices[existing_key]["last_updated"] = datetime.now(timezone.utc).isoformat()

        self._save_inventory()
        self.my_key = existing_key
        logger.info(f"Device registered/updated in inventory: '{existing_key}' (device_id={self.device_id})")
        return devices[existing_key]

    # ------------------------------------------------------------------ #
    #  Hardware Detection                                                   #
    # ------------------------------------------------------------------ #

    def _update_hardware(self, device_entry: dict):
        """Detect hardware and update device entry. Logs changes."""
        old_hw = device_entry.get("hardware", {})
        new_hw = self._detect_hardware()

        changed = []
        for key, val in new_hw.items():
            if old_hw.get(key) != val:
                changed.append(f"{key}: {old_hw.get(key)} -> {val}")

        if changed:
            logger.info(f"Hardware changes detected: {', '.join(changed)}")
        else:
            logger.debug("Hardware unchanged")

        device_entry["hardware"] = new_hw

    def _detect_hardware(self) -> dict:
        """Collect CPU, RAM, GPU info."""
        hw = {}
        try:
            hw["cpu_cores"] = os.cpu_count()
            hw["platform"] = platform.machine()
            hw["os"] = platform.system()
            hw["os_version"] = platform.version()[:80]
        except Exception as e:
            logger.warning(f"CPU detection failed: {e}")

        try:
            import psutil
            mem = psutil.virtual_memory()
            hw["ram_total_gb"] = round(mem.total / (1024**3), 1)
        except ImportError:
            try:
                with open("/proc/meminfo") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            hw["ram_total_gb"] = round(kb / (1024**2), 1)
                            break
            except Exception as e:
                logger.warning(f"RAM detection failed: {e}")

        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                gpus = []
                for line in result.stdout.strip().splitlines():
                    parts = line.split(",")
                    if len(parts) >= 2:
                        gpus.append({"name": parts[0].strip(), "vram": parts[1].strip()})
                hw["gpus"] = gpus
                logger.debug(f"GPUs: {gpus}")
        except Exception:
            hw["gpus"] = []

        return hw

    def _update_network(self, device_entry: dict):
        """Detect network interfaces and IPs, log changes."""
        old_net = device_entry.get("network", {})
        new_net = self._detect_network()

        old_ips = set(old_net.get("ip_addresses", []))
        new_ips = set(new_net.get("ip_addresses", []))
        added = new_ips - old_ips
        removed = old_ips - new_ips
        if added:
            logger.info(f"New IP addresses detected: {added}")
        if removed:
            logger.info(f"IP addresses removed: {removed}")
        if not added and not removed:
            logger.debug("Network unchanged")

        device_entry["network"] = new_net

    def _detect_network(self) -> dict:
        """Collect network interfaces and IPs."""
        net = {}
        try:
            import socket as _socket
            hostname = _socket.gethostname()
            ips = _socket.gethostbyname_ex(hostname)[2]
            net["ip_addresses"] = [ip for ip in ips if not ip.startswith("127.")]
            net["hostname"] = hostname
        except Exception as e:
            logger.warning(f"Basic network detection failed: {e}")

        try:
            import psutil
            interfaces = {}
            for iface, addrs in psutil.net_if_addrs().items():
                iface_ips = []
                for addr in addrs:
                    if addr.family == 2:  # AF_INET
                        iface_ips.append(addr.address)
                if iface_ips:
                    interfaces[iface] = iface_ips
            net["interfaces"] = interfaces
        except ImportError:
            pass

        return net

    # ------------------------------------------------------------------ #
    #  Convenience                                                          #
    # ------------------------------------------------------------------ #

    def get_my_device(self) -> Optional[dict]:
        """Return this device's inventory entry."""
        return self.inventory["devices"].get(getattr(self, "my_key", self.hostname))

    def get_all_devices(self) -> dict:
        """Return all known devices."""
        return self.inventory.get("devices", {})

    def get_peer_devices(self) -> dict:
        """Return all devices that are NOT this device."""
        return {
            k: v for k, v in self.get_all_devices().items()
            if v.get("device_id") != self.device_id
        }
