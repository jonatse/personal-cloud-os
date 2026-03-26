"""
Access Control Middleware for Personal Cloud OS.

Provides access control based on trust levels for the Identity & Trust System.
"""
import logging
from typing import Any, Callable, Dict, Optional, Tuple

from core.version import __version__
from core.identity import IdentityManager

logger = logging.getLogger(__name__)

RESOURCE_SYNC = "/sync"
RESOURCE_COMPUTE = "/compute"
RESOURCE_HOME = "/home"
RESOURCE_COMMAND = "/cmd"

TRUST_PERSONAL = "personal"
TRUST_CIRCLE = "circle"
TRUST_UNKNOWN = "unknown"


class AccessControl:
    """
    Access control based on trust levels from IdentityManager.
    """

    def __init__(self, identity_manager: IdentityManager):
        self._identity_manager = identity_manager
        self._handlers: Dict[str, Tuple[Callable, str]] = {}
        logger.info(f"v{__version__} AccessControl initialized")

    def check_access(self, identity_hash: str, resource: str) -> bool:
        """
        Checks if identity can access the given resource.

        Args:
            identity_hash: Hex string of identity hash
            resource: Resource path to access

        Returns:
            bool: True if access is granted, False otherwise
        """
        trust_level = self._identity_manager.get_trust_level(identity_hash)

        logger.debug(f"v{__version__} Access check: identity={identity_hash[:16]}..., resource={resource}, trust={trust_level}")

        if resource.startswith(RESOURCE_SYNC):
            return self._check_sync_access(trust_level, resource)
        elif resource.startswith(RESOURCE_COMPUTE):
            return self._check_compute_access(trust_level)
        elif resource.startswith(RESOURCE_HOME):
            return self._check_home_access(trust_level)
        elif resource.startswith(RESOURCE_COMMAND):
            return self._check_command_access(trust_level)

        logger.warning(f"v{__version__} Unknown resource type: {resource}")
        return False

    def _check_sync_access(self, trust_level: str, resource: str) -> bool:
        """
        Check access for /sync/* resources.
        - personal: full access to all files
        - circle: access to shared folders only
        - unknown: no access
        """
        if trust_level == TRUST_PERSONAL:
            return True
        elif trust_level == TRUST_CIRCLE:
            if "/shared" in resource or "/circle" in resource:
                return True
            return False
        return False

    def _check_compute_access(self, trust_level: str) -> bool:
        """
        Check access for /compute/* resources.
        - personal: full access
        - circle: no access
        - unknown: no access
        """
        return trust_level == TRUST_PERSONAL

    def _check_home_access(self, trust_level: str) -> bool:
        """
        Check access for /home/* resources.
        - personal: full access
        - circle: no access
        - unknown: no access
        """
        return trust_level == TRUST_PERSONAL

    def _check_command_access(self, trust_level: str) -> bool:
        """
        Check access for /cmd/* resources.
        - personal: full access
        - circle: no access
        - unknown: no access
        """
        return trust_level == TRUST_PERSONAL

    def register_handler(self, path: str, handler: Callable, min_trust: str) -> None:
        """
        Registers a handler with minimum trust level requirement.

        Args:
            path: Resource path pattern
            handler: Handler function to call
            min_trust: Minimum trust level required ("personal", "circle", "unknown")
        """
        self._handlers[path] = (handler, min_trust)
        logger.info(f"v{__version__} Registered handler: path={path}, min_trust={min_trust}")

    def get_handler(self, path: str, identity_hash: str) -> Optional[Callable]:
        """
        Gets the appropriate handler for the path if access is granted.

        Args:
            path: Resource path
            identity_hash: Identity hash requesting access

        Returns:
            Handler function if access granted, None otherwise
        """
        if not self.check_access(identity_hash, path):
            logger.warning(f"v{__version__} Access denied: identity={identity_hash[:16]}..., path={path}")
            return None

        for pattern, (handler, min_trust) in self._handlers.items():
            if path.startswith(pattern):
                trust_level = self._identity_manager.get_trust_level(identity_hash)
                if self._trust_sufficient(trust_level, min_trust):
                    return handler

        return None

    def _trust_sufficient(self, actual: str, required: str) -> bool:
        """
        Check if actual trust level meets required level.

        Trust hierarchy: personal > circle > unknown
        """
        levels = {TRUST_UNKNOWN: 0, TRUST_CIRCLE: 1, TRUST_PERSONAL: 2}
        actual_level = levels.get(actual, 0)
        required_level = levels.get(required, 0)
        return actual_level >= required_level