"""
Contact Registry for Personal Cloud OS

Wave 1 of the data-centric OS architecture — turns the Circle-based
identity system into a full contact system with entity model support.
"""
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.version import __version__

logger = logging.getLogger(__name__)

DEFAULT_STORAGE_PATH = os.path.expanduser("~/.local/share/pcos/contacts/")


class ContactRegistry:
    """
    Manages contacts as the primary entity in the data-centric OS.

    Each contact = identity_hash + metadata (display_name, phone_number,
    avatar, devices[], trust_level, custom_fields) with cross-references
    to other entities and vector-clock-based sync conflict detection.
    """

    def __init__(
        self,
        identity_manager,
        device_manager,
        event_bus=None,
        storage_path=None,
    ):
        """
        Initialize the Contact Registry.

        Args:
            identity_manager: IdentityManager instance for trust-level derivation.
            device_manager: DeviceManager instance for device_id and vector clocks.
            event_bus: Optional EventBus instance for publishing events.
            storage_path: Directory for contacts.json. Defaults to ~/.local/share/pcos/contacts/.
        """
        self.identity_manager = identity_manager
        self.device_manager = device_manager
        self.event_bus = event_bus
        self.storage_path = storage_path or DEFAULT_STORAGE_PATH

        os.makedirs(self.storage_path, exist_ok=True)
        self.contacts_file = os.path.join(self.storage_path, "contacts.json")

        self.contacts: Dict[str, dict] = {}
        self._load()

        logger.info(f"v{__version__} ContactRegistry initialized ({len(self.contacts)} contacts loaded)")

    # ------------------------------------------------------------------ #
    #  CRUD                                                                 #
    # ------------------------------------------------------------------ #

    def add_contact(
        self,
        identity_hash: str,
        display_name: str,
        phone_number: Optional[str] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """
        Create a new contact entry.

        Args:
            identity_hash: RNS.Identity hex hash.
            display_name: Human-readable name.
            phone_number: Optional phone number.
            custom_fields: Optional arbitrary key-value pairs.

        Returns:
            The contact dict.

        Raises:
            ValueError: If identity_hash is not a valid hex string.
        """
        if not self._is_valid_hex(identity_hash):
            raise ValueError(f"Invalid identity_hash (must be hex string): {identity_hash}")

        trust_level = self.identity_manager.get_trust_level(identity_hash)
        now = datetime.now(timezone.utc).isoformat()

        contact = {
            "id": uuid.uuid4().hex,
            "identity_hash": identity_hash,
            "display_name": display_name,
            "phone_number": phone_number,
            "avatar": None,
            "trust_level": trust_level,
            "devices": [],
            "custom_fields": custom_fields or {},
            "refs": {},
            "created_at": now,
            "updated_at": now,
            "vector_clock": {},
            "notes": None,
        }

        self.contacts[contact["id"]] = contact
        self._save()

        if self.event_bus:
            from core.events import Event, Events
            self.event_bus.publish(
                type=Events.CONTACT_ADDED,
                data={"contact_id": contact["id"], "identity_hash": identity_hash},
                source="contact_registry",
            )

        logger.info(f"Added contact: {display_name} ({contact['id'][:8]}...)")
        return contact

    def update_contact(self, contact_id: str, **kwargs) -> dict:
        """
        Update fields on an existing contact.

        Args:
            contact_id: The contact UUID.
            **kwargs: Fields to update.

        Returns:
            The updated contact dict.

        Raises:
            KeyError: If contact_id does not exist.
        """
        if contact_id not in self.contacts:
            raise KeyError(f"Contact not found: {contact_id}")

        contact = self.contacts[contact_id]

        for key, value in kwargs.items():
            if key in ("id", "identity_hash", "created_at", "vector_clock"):
                continue
            contact[key] = value

        self._bump_vector_clock(contact)
        contact["updated_at"] = datetime.now(timezone.utc).isoformat()

        self._save()

        if self.event_bus:
            from core.events import Event, Events
            self.event_bus.publish(
                type=Events.CONTACT_UPDATED,
                data={"contact_id": contact_id},
                source="contact_registry",
            )

        logger.info(f"Updated contact: {contact_id[:8]}...")
        return contact

    def remove_contact(self, contact_id: str) -> bool:
        """
        Remove a contact by ID.

        Args:
            contact_id: The contact UUID.

        Returns:
            True if removed, False if not found.
        """
        if contact_id not in self.contacts:
            return False

        del self.contacts[contact_id]
        self._save()

        if self.event_bus:
            from core.events import Event, Events
            self.event_bus.publish(
                type=Events.CONTACT_REMOVED,
                data={"contact_id": contact_id},
                source="contact_registry",
            )

        logger.info(f"Removed contact: {contact_id[:8]}...")
        return True

    # ------------------------------------------------------------------ #
    #  Queries                                                              #
    # ------------------------------------------------------------------ #

    def get_contact(self, contact_id: str) -> Optional[dict]:
        """
        Return a contact by ID, or None.
        """
        return self.contacts.get(contact_id)

    def get_contact_by_identity(self, identity_hash: str) -> Optional[dict]:
        """
        Return a contact by RNS identity hash, or None.
        """
        for contact in self.contacts.values():
            if contact["identity_hash"] == identity_hash:
                return contact
        return None

    def list_contacts(self, trust_level: Optional[str] = None) -> List[dict]:
        """
        Return all contacts, optionally filtered by trust_level.

        Results are sorted by display_name.
        """
        contacts = list(self.contacts.values())
        if trust_level:
            contacts = [c for c in contacts if c["trust_level"] == trust_level]
        return sorted(contacts, key=lambda c: c["display_name"].lower())

    def search_contacts(self, query: str) -> List[dict]:
        """
        Search display_name, phone_number, notes, and custom_fields.

        Case-insensitive substring match.
        """
        query_lower = query.lower()
        results = []

        for contact in self.contacts.values():
            if query_lower in contact["display_name"].lower():
                results.append(contact)
                continue
            if contact["phone_number"] and query_lower in contact["phone_number"].lower():
                results.append(contact)
                continue
            if contact["notes"] and query_lower in contact["notes"].lower():
                results.append(contact)
                continue
            for field_value in contact["custom_fields"].values():
                if isinstance(field_value, str) and query_lower in field_value.lower():
                    results.append(contact)
                    break

        return results

    # ------------------------------------------------------------------ #
    #  Devices                                                              #
    # ------------------------------------------------------------------ #

    def register_device(self, contact_id: str, device_info: dict) -> bool:
        """
        Register a device under a contact.

        Args:
            contact_id: The contact UUID.
            device_info: Dict with device_id, hostname, identity_path, hardware.

        Returns:
            True if registered/updated.
        """
        contact = self.contacts.get(contact_id)
        if not contact:
            return False

        device_entry = {
            "device_id": device_info.get("device_id", ""),
            "hostname": device_info.get("hostname", ""),
            "identity_path": device_info.get("identity_path", ""),
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "hardware": device_info.get("hardware", {}),
        }

        existing_index = None
        for i, dev in enumerate(contact["devices"]):
            if dev["device_id"] == device_entry["device_id"]:
                existing_index = i
                break

        if existing_index is not None:
            contact["devices"][existing_index] = device_entry
            logger.info(f"Updated device {device_entry['device_id']} on contact {contact_id[:8]}...")
        else:
            contact["devices"].append(device_entry)
            logger.info(f"Registered device {device_entry['device_id']} on contact {contact_id[:8]}...")

        self._bump_vector_clock(contact)
        contact["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

        if self.event_bus:
            from core.events import Event, Events
            self.event_bus.publish(
                type=Events.CONTACT_DEVICE_REGISTERED,
                data={"contact_id": contact_id, "device_id": device_entry["device_id"]},
                source="contact_registry",
            )

        return True

    def remove_device(self, contact_id: str, device_id: str) -> bool:
        """
        Remove a device from a contact.

        Args:
            contact_id: The contact UUID.
            device_id: The device identifier.

        Returns:
            True if removed, False if not found.
        """
        contact = self.contacts.get(contact_id)
        if not contact:
            return False

        before = len(contact["devices"])
        contact["devices"] = [d for d in contact["devices"] if d["device_id"] != device_id]

        if len(contact["devices"]) == before:
            return False

        self._bump_vector_clock(contact)
        contact["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

        if self.event_bus:
            from core.events import Event, Events
            self.event_bus.publish(
                type=Events.CONTACT_DEVICE_REMOVED,
                data={"contact_id": contact_id, "device_id": device_id},
                source="contact_registry",
            )

        logger.info(f"Removed device {device_id} from contact {contact_id[:8]}...")
        return True

    # ------------------------------------------------------------------ #
    #  Cross-references                                                     #
    # ------------------------------------------------------------------ #

    def add_cross_ref(self, contact_id: str, ref_type: str, ref_id: str) -> bool:
        """
        Add a cross-reference from this contact to another entity.

        Args:
            contact_id: The contact UUID.
            ref_type: Type of reference (location, transaction, message, etc.).
            ref_id: UUID of the referenced entity.

        Returns:
            True if added.
        """
        contact = self.contacts.get(contact_id)
        if not contact:
            return False

        if ref_type not in contact["refs"]:
            contact["refs"][ref_type] = []

        if ref_id not in contact["refs"][ref_type]:
            contact["refs"][ref_type].append(ref_id)
            self._bump_vector_clock(contact)
            contact["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()

            if self.event_bus:
                from core.events import Event, Events
                self.event_bus.publish(
                    type=Events.CONTACT_REF_ADDED,
                    data={"contact_id": contact_id, "ref_type": ref_type, "ref_id": ref_id},
                    source="contact_registry",
                )

            logger.info(f"Added {ref_type} ref {ref_id[:8]}... to contact {contact_id[:8]}...")

        return True

    def get_cross_refs(self, contact_id: str, ref_type: Optional[str] = None) -> Any:
        """
        Return cross-references for a contact.

        If ref_type is specified, returns the list of ref_ids for that type.
        Otherwise returns the entire refs dict.
        """
        contact = self.contacts.get(contact_id)
        if not contact:
            return [] if ref_type else {}

        if ref_type:
            return contact["refs"].get(ref_type, [])
        return contact["refs"]

    # ------------------------------------------------------------------ #
    #  Merge / Dedup                                                        #
    # ------------------------------------------------------------------ #

    def merge_contact(self, source_id: str, target_id: str) -> dict:
        """
        Merge two contact entries (deduplication).

        Combines devices, custom_fields, and refs from source into target.
        Removes the source contact.

        Args:
            source_id: The contact to merge from.
            target_id: The contact to merge into.

        Returns:
            The merged target contact dict.

        Raises:
            KeyError: If either contact does not exist.
        """
        if source_id not in self.contacts:
            raise KeyError(f"Source contact not found: {source_id}")
        if target_id not in self.contacts:
            raise KeyError(f"Target contact not found: {target_id}")

        source = self.contacts[source_id]
        target = self.contacts[target_id]

        # Merge devices (by device_id, source wins on conflicts)
        target_device_ids = {d["device_id"] for d in target["devices"]}
        for device in source["devices"]:
            if device["device_id"] not in target_device_ids:
                target["devices"].append(device)

        # Merge custom_fields (target wins on key conflicts)
        for key, value in source["custom_fields"].items():
            if key not in target["custom_fields"]:
                target["custom_fields"][key] = value

        # Merge refs (combine lists, deduplicate)
        for ref_type, ref_ids in source["refs"].items():
            if ref_type not in target["refs"]:
                target["refs"][ref_type] = []
            for ref_id in ref_ids:
                if ref_id not in target["refs"][ref_type]:
                    target["refs"][ref_type].append(ref_id)

        # Keep the more informative display_name if target is empty-ish
        if not target["display_name"] and source["display_name"]:
            target["display_name"] = source["display_name"]
        if not target["phone_number"] and source["phone_number"]:
            target["phone_number"] = source["phone_number"]
        if not target["notes"] and source["notes"]:
            target["notes"] = source["notes"]

        # Remove source
        del self.contacts[source_id]

        self._bump_vector_clock(target)
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

        if self.event_bus:
            from core.events import Event, Events
            self.event_bus.publish(
                type=Events.CONTACT_MERGED,
                data={"source_id": source_id, "target_id": target_id},
                source="contact_registry",
            )

        logger.info(f"Merged contact {source_id[:8]}... into {target_id[:8]}...")
        return target

    # ------------------------------------------------------------------ #
    #  Import / Export                                                      #
    # ------------------------------------------------------------------ #

    def export_contact(self, contact_id: str) -> str:
        """
        Export a contact as JSON string (for sharing/backup).

        Excludes internal fields: vector_clock, created_at, updated_at.
        """
        contact = self.contacts.get(contact_id)
        if not contact:
            raise KeyError(f"Contact not found: {contact_id}")

        export = {k: v for k, v in contact.items() if k not in ("vector_clock", "created_at", "updated_at")}
        return json.dumps(export, indent=2)

    def import_contact(self, json_string: str) -> dict:
        """
        Import a contact from JSON string.

        Generates a new ID if there is a conflict.

        Returns:
            The imported contact dict.
        """
        try:
            data = json.loads(json_string)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

        now = datetime.now(timezone.utc).isoformat()

        contact_id = data.get("id", uuid.uuid4().hex)
        if contact_id in self.contacts:
            contact_id = uuid.uuid4().hex

        contact = {
            "id": contact_id,
            "identity_hash": data.get("identity_hash", ""),
            "display_name": data.get("display_name", ""),
            "phone_number": data.get("phone_number"),
            "avatar": data.get("avatar"),
            "trust_level": data.get("trust_level", "unknown"),
            "devices": data.get("devices", []),
            "custom_fields": data.get("custom_fields", {}),
            "refs": data.get("refs", {}),
            "created_at": now,
            "updated_at": now,
            "vector_clock": {},
            "notes": data.get("notes"),
        }

        self.contacts[contact["id"]] = contact
        self._save()

        if self.event_bus:
            from core.events import Event, Events
            self.event_bus.publish(
                type=Events.CONTACT_IMPORTED,
                data={"contact_id": contact["id"]},
                source="contact_registry",
            )

        logger.info(f"Imported contact: {contact['display_name']} ({contact['id'][:8]}...)")
        return contact

    # ------------------------------------------------------------------ #
    #  Stats                                                                #
    # ------------------------------------------------------------------ #

    def get_stats(self) -> dict:
        """
        Return summary statistics about the contact registry.
        """
        contacts = list(self.contacts.values())
        by_trust = {}
        total_devices = 0
        contacts_with_refs = 0

        for contact in contacts:
            tl = contact["trust_level"]
            by_trust[tl] = by_trust.get(tl, 0) + 1
            total_devices += len(contact["devices"])
            if any(len(refs) > 0 for refs in contact["refs"].values()):
                contacts_with_refs += 1

        return {
            "total_contacts": len(contacts),
            "by_trust_level": by_trust,
            "total_devices": total_devices,
            "contacts_with_refs": contacts_with_refs,
        }

    # ------------------------------------------------------------------ #
    #  Internal                                                             #
    # ------------------------------------------------------------------ #

    def _save(self):
        """
        Save all contacts to contacts.json using atomic write.

        Writes to a .tmp file first, then os.replace() for atomicity.
        """
        try:
            fd, tmp_path = tempfile.mkstemp(dir=self.storage_path, suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self.contacts, f, indent=2)
                os.replace(tmp_path, self.contacts_file)
            except Exception:
                os.unlink(tmp_path)
                raise
        except Exception as e:
            logger.error(f"Failed to save contacts: {e}")

    def _load(self):
        """
        Load contacts from contacts.json.

        Returns an empty dict if the file doesn't exist.
        """
        if not os.path.exists(self.contacts_file):
            logger.info("No contacts file found, starting fresh")
            return

        try:
            with open(self.contacts_file, "r") as f:
                self.contacts = json.load(f)
            logger.info(f"Loaded {len(self.contacts)} contacts from disk")
        except Exception as e:
            logger.error(f"Failed to load contacts: {e}")
            self.contacts = {}

    def _bump_vector_clock(self, contact: dict):
        """
        Increment the vector clock entry for this device.
        """
        device_id = self.device_manager.device_id
        contact["vector_clock"][device_id] = contact["vector_clock"].get(device_id, 0) + 1

    @staticmethod
    def _is_valid_hex(s: str) -> bool:
        """Check if a string is a valid hex string."""
        try:
            int(s, 16)
            return True
        except (ValueError, TypeError):
            return False
