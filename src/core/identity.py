"""
Identity Manager for Personal Cloud OS

Manages personal identity and circles for the Identity & Trust System
using Reticulum's RNS.Identity.
"""
import base64
import json
import logging
import os
from typing import List, Optional

import RNS

from core.version import __version__

logger = logging.getLogger(__name__)

IDENTITY_PATH_DEFAULT = os.path.expanduser("~/.reticulum/storage/identities/pcos")
CIRCLES_BASE_PATH = os.path.expanduser("~/.local/share/pcos/circles")


class IdentityManager:
    """
    Manages personal RNS identity and circle-based trust relationships.
    """

    def __init__(self, identity_path: str = None):
        self._identity_path = identity_path or IDENTITY_PATH_DEFAULT
        self._identity: Optional[RNS.Identity] = None
        self._circles_dir = CIRCLES_BASE_PATH
        self._contact_registry = None
        logger.info(f"v{__version__} IdentityManager initialized")

    def get_identity_path(self) -> str:
        """Returns the RNS identity file path."""
        return self._identity_path

    def load_or_create_identity(self) -> RNS.Identity:
        """
        Loads existing identity or creates new one if not found.
        
        Returns:
            RNS.Identity: The loaded or created identity
        """
        if os.path.exists(self._identity_path):
            self._identity = RNS.Identity.from_file(self._identity_path)
            logger.info(f"v{__version__} Loaded identity: {self._identity.hash.hex()[:16]}...")
        else:
            os.makedirs(os.path.dirname(self._identity_path), exist_ok=True)
            self._identity = RNS.Identity()
            self._identity.to_file(self._identity_path)
            logger.info(f"v{__version__} Created new identity at {self._identity_path}")

        return self._identity

    def get_identity_hash(self) -> str:
        """
        Returns the identity hash as hex string.
        
        Returns:
            str: Hex string of identity hash
        """
        if self._identity is None:
            self.load_or_create_identity()
        return self._identity.hash.hex()

    def export_identity(self) -> str:
        """
        Returns identity as base64 string for sharing.
        
        Returns:
            str: Base64 encoded identity
        """
        if self._identity is None:
            self.load_or_create_identity()
        identity_bytes = self._identity.get_public_key()
        return base64.b64encode(identity_bytes).decode()

    def import_identity(self, base64_string: str) -> RNS.Identity:
        """
        Imports identity from base64 string.
        
        Args:
            base64_string: Base64 encoded identity
            
        Returns:
            RNS.Identity: The imported identity
        """
        identity_bytes = base64.b64decode(base64_string)
        identity = RNS.Identity(create_keys=False)
        identity.load_public_key(identity_bytes)
        logger.info(f"v{__version__} Imported identity: {identity.hash.hex()[:16]}...")
        return identity

    def list_circles(self) -> List[str]:
        """
        Returns list of circle names.
        
        Returns:
            List[str]: List of circle names
        """
        if not os.path.exists(self._circles_dir):
            return []
        
        circles = []
        for item in os.listdir(self._circles_dir):
            circle_path = os.path.join(self._circles_dir, item)
            if os.path.isdir(circle_path):
                identity_file = os.path.join(circle_path, "identity")
                if os.path.exists(identity_file):
                    circles.append(item)
        return sorted(circles)

    def create_circle(self, name: str) -> RNS.Identity:
        """
        Creates a new circle identity.
        
        Args:
            name: Name of the circle
            
        Returns:
            RNS.Identity: The created circle identity
        """
        circle_dir = os.path.join(self._circles_dir, name)
        os.makedirs(circle_dir, exist_ok=True)
        
        identity_file = os.path.join(circle_dir, "identity")
        members_file = os.path.join(circle_dir, "members.json")
        
        circle_identity = RNS.Identity()
        circle_identity.to_file(identity_file)
        
        if not os.path.exists(members_file):
            with open(members_file, "w") as f:
                json.dump([], f)
        
        logger.info(f"v{__version__} Created circle: {name}")
        return circle_identity

    def get_circle(self, name: str) -> Optional[RNS.Identity]:
        """
        Returns circle identity.
        
        Args:
            name: Name of the circle
            
        Returns:
            RNS.Identity or None: The circle identity if exists
        """
        identity_file = os.path.join(self._circles_dir, name, "identity")
        if os.path.exists(identity_file):
            return RNS.Identity.from_file(identity_file)
        return None

    def add_to_circle(self, name: str, identity_base64: str) -> bool:
        """
        Adds an identity to a circle.
        
        Args:
            name: Name of the circle
            identity_base64: Base64 encoded identity to add
            
        Returns:
            bool: True if added successfully
        """
        circle_dir = os.path.join(self._circles_dir, name)
        members_file = os.path.join(circle_dir, "members.json")
        
        if not os.path.exists(circle_dir):
            logger.warning(f"v{__version__} Circle does not exist: {name}")
            return False
        
        identity = self.import_identity(identity_base64)
        identity_hash = identity.hash.hex()
        
        members = []
        if os.path.exists(members_file):
            with open(members_file, "r") as f:
                members = json.load(f)
        
        if identity_hash not in members:
            members.append(identity_hash)
            with open(members_file, "w") as f:
                json.dump(members, f)
            logger.info(f"v{__version__} Added identity to circle {name}: {identity_hash[:16]}...")

            # Also create a contact entry if registry is available
            if self._contact_registry is not None:
                try:
                    existing = self._contact_registry.get_contact_by_identity(identity_hash)
                    if existing is None:
                        self._contact_registry.add_contact(
                            identity_hash=identity_hash,
                            display_name=f"Contact ({identity_hash[:8]})",
                        )
                        logger.info(f"Auto-created contact for circle member: {identity_hash[:16]}...")
                except Exception as e:
                    logger.warning(f"Failed to auto-create contact for circle member: {e}")
        
        return True

    def remove_from_circle(self, name: str, identity_hash: str) -> bool:
        """
        Removes identity from circle.
        
        Args:
            name: Name of the circle
            identity_hash: Hex string of identity hash to remove
            
        Returns:
            bool: True if removed successfully
        """
        circle_dir = os.path.join(self._circles_dir, name)
        members_file = os.path.join(circle_dir, "members.json")
        
        if not os.path.exists(members_file):
            logger.warning(f"v{__version__} Circle does not exist: {name}")
            return False
        
        with open(members_file, "r") as f:
            members = json.load(f)
        
        if identity_hash in members:
            members.remove(identity_hash)
            with open(members_file, "w") as f:
                json.dump(members, f)
            logger.info(f"v{__version__} Removed identity from circle {name}: {identity_hash[:16]}...")
            return True
        
        logger.warning(f"v{__version__} Identity not found in circle {name}")
        return False

    def get_trust_level(self, identity_hash: str) -> str:
        """
        Returns trust level for an identity.
        
        Args:
            identity_hash: Hex string of identity hash
            
        Returns:
            str: "personal", "circle", or "unknown"
        """
        personal_hash = self.get_identity_hash()
        if identity_hash == personal_hash:
            return "personal"
        
        for circle_name in self.list_circles():
            members_file = os.path.join(self._circles_dir, circle_name, "members.json")
            if os.path.exists(members_file):
                with open(members_file, "r") as f:
                    members = json.load(f)
                if identity_hash in members:
                    return "circle"
        
        return "unknown"

    def set_contact_registry(self, contact_registry):
        """Set the contact registry for identity-contact integration."""
        self._contact_registry = contact_registry
        logger.info("Contact registry linked to IdentityManager")

    def get_contact_for_identity(self, identity_hash) -> Optional[dict]:
        """
        Returns contact info for an identity hash if available.
        
        Args:
            identity_hash: Hex string of identity hash
            
        Returns:
            dict or None: Contact info if found, None otherwise
        """
        if self._contact_registry is not None:
            return self._contact_registry.get_contact_by_identity(identity_hash)
        return None

    def get_identity_context(self, identity_hash) -> dict:
        """
        Returns full context for an identity: trust level + contact info.
        
        Args:
            identity_hash: Hex string of identity hash
            
        Returns:
            dict: {"trust_level": str, "contact": dict|None, "is_known": bool}
        """
        trust_level = self.get_trust_level(identity_hash)
        contact = self.get_contact_for_identity(identity_hash)
        return {
            "trust_level": trust_level,
            "contact": contact,
            "is_known": trust_level != "unknown" or contact is not None
        }