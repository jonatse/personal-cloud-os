"""Configuration management for Personal Cloud OS."""
import os
import json
from pathlib import Path
from typing import Any


class Config:
    """Application configuration manager."""
    
    DEFAULT_CONFIG = {
        "app": {
            "name": "PersonalCloudOS",
            "version": "0.1.0",
            "debug": False
        },
        "reticulum": {
            "identity_path": "~/.reticulum/storage/identities/pcos",
            "announce_interval": 30,
            "share_instance": True
        },
        "discovery": {
            "enabled": True,
            "port": 45678,
            "broadcast_interval": 5,
            "peer_timeout": 30
        },
        "sync": {
            "enabled": True,
            "sync_interval": 60,
            "conflict_resolution": "newest",  # newest, oldest, manual
            "encrypted": True
        },
        "container": {
            "image": "alpine:latest",
            "name": "personal-cloud-os",
            "auto_start": True,
            "mount_points": []
        },
        "network": {
            "bind_address": "0.0.0.0",
            "max_peers": 10
        }
    }
    
    def __init__(self, config_path: str = None):
        """Initialize configuration."""
        self.config_path = config_path or os.path.expanduser("~/.config/pcos/config.json")
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        """Load configuration from file or use defaults."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    user_config = json.load(f)
                return self._merge_configs(self.DEFAULT_CONFIG, user_config)
            except (json.JSONDecodeError, IOError):
                pass
        return self.DEFAULT_CONFIG.copy()
    
    def _merge_configs(self, default: dict, user: dict) -> dict:
        """Merge user config with defaults."""
        result = default.copy()
        for key, value in user.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot-notation key."""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value
    
    def set(self, key: str, value: Any):
        """Set configuration value by dot-notation key."""
        keys = key.split('.')
        config = self.config
        for k in keys[:-1]:
            config = config.setdefault(k, {})
        config[keys[-1]] = value
    
    def save(self):
        """Save configuration to file."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)


# Global config instance
config = Config()
