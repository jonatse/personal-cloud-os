"""Personal Cloud OS - Main Entry Point."""
import asyncio
import logging
import signal
import sys
import os

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import Config
from core.events import Event, Events, event_bus
from core.logger import setup_logging, get_logger
from services.reticulum_peer import ReticulumPeerService
from services.discovery import PeerDiscoveryService
from services.peer_link import PeerLinkService
from services.sync import SyncEngine
from container.manager import ContainerManager
from ui.launcher import AppLauncher


logger = get_logger(__name__)


class PersonalCloudOS:
    """
    Main application class that orchestrates all services.
    
    Architecture:
    ┌─────────────────────────────────────────────────────────────────┐
    │                         THE APP                                 │
    │                                                                  │
    │   ┌───────────────────────────────────────────────────────────┐ │
    │   │  RETICULUM NETWORK LAYER (Background)                    │ │
    │   │  • Embedded RNS library (no rnsd daemon)                │ │
    │   │  • Identity-based peer discovery                      │ │
    │   │  • Encrypted P2P links                                  │ │
    │   └───────────────────────────────────────────────────────────┘ │
    │                              │                                   │
    │                              ▼                                   │
    │   ┌───────────────────────────────────────────────────────────┐ │
    │   │  PEER DISCOVERY (Background)                            │ │
    │   │  • Uses Reticulum for peer finding                       │ │
    │   │  • Same identity = automatic discovery                  │ │
    │   └───────────────────────────────────────────────────────────┘ │
    │                              │                                   │
    │                              ▼                                   │
    │   ┌───────────────────────────────────────────────────────────┐ │
    │   │  SYNC ENGINE (Background)                                │ │
    │   │  • Syncs files with discovered peers                     │ │
    │   │  • Encrypted transfers via Reticulum links              │ │
    │   └───────────────────────────────────────────────────────────┘ │
    │                              │                                   │
    │                              ▼                                   │
    │   ┌───────────────────────────────────────────────────────────┐ │
    │   │  CONTAINER WITH YOUR LINUX OS (Background)              │ │
    │   │  • Alpine/Debian environment                             │ │
    │   │  • Your files, configs, terminal                         │ │
    │   └───────────────────────────────────────────────────────────┘ │
    │                              │                                   │
    │                              ▼                                   │
    │   ┌───────────────────────────────────────────────────────────┐ │
    │   │  APP LAUNCHER / DISPLAY                                  │ │
    │   │  • Open calendar, terminal, files                        │ │
    │   │  • Display peer status, sync status                      │ │
    │   └───────────────────────────────────────────────────────────┘ │
    └─────────────────────────────────────────────────────────────────┘
    """
    
    def __init__(self):
        """Initialize the application."""
        # Load configuration
        self.config = Config()
        
        # Setup logging
        setup_logging(
            level="DEBUG" if self.config.get("app.debug") else "INFO",
            log_file=os.path.expanduser("~/.local/share/pcos/logs/app.log")
        )
        
        logger.info("=" * 60)
        logger.info("Personal Cloud OS Starting...")
        logger.info("=" * 60)
        
        # Initialize Reticulum peer service (core networking)
        self.reticulum_service = ReticulumPeerService(self.config, event_bus)
        
        # Initialize peer discovery (uses Reticulum)
        self.discovery_service = PeerDiscoveryService(self.config, event_bus)
        self.discovery_service.set_reticulum_service(self.reticulum_service)
        
        # Initialize peer link service (encrypted P2P)
        self.peer_link_service = PeerLinkService(
            self.config, 
            event_bus, 
            self.reticulum_service
        )
        
        # Initialize sync engine (uses peer links)
        self.sync_engine = SyncEngine(
            self.config, 
            event_bus, 
            self.discovery_service,
            self.peer_link_service
        )
        
        # Initialize container manager
        self.container_manager = ContainerManager(self.config, event_bus)
        
        # Initialize UI
        self.launcher = AppLauncher(
            self.config,
            event_bus,
            self.discovery_service,
            self.sync_engine,
            self.container_manager
        )
        
        # Setup signal handlers
        self._setup_signals()
        
        # Track running state
        self._running = False
    
    def _setup_signals(self):
        """Setup signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down...")
        asyncio.create_task(self.stop())
    
    async def start(self):
        """Start all services."""
        if self._running:
            logger.warning("Application already running")
            return
        
        logger.info("Starting services...")
        self._running = True
        
        # Start Reticulum networking first (foundation for everything)
        try:
            await self.reticulum_service.start()
        except Exception as e:
            logger.error(f"Failed to start Reticulum: {e}")
            logger.warning("Continuing without networking...")
        
        # Start container (if auto-start enabled)
        if self.config.get("container.auto_start", True):
            try:
                await self.container_manager.start()
            except Exception as e:
                logger.error(f"Failed to start container: {e}")
        
        # Start peer discovery
        try:
            await self.discovery_service.start()
        except Exception as e:
            logger.error(f"Failed to start discovery service: {e}")
        
        # Start peer link service
        try:
            await self.peer_link_service.start()
        except Exception as e:
            logger.error(f"Failed to start peer link service: {e}")
        
        # Start sync engine
        try:
            await self.sync_engine.start()
        except Exception as e:
            logger.error(f"Failed to start sync engine: {e}")
        
        logger.info("All services started!")
        
        # Publish status
        await event_bus.publish(Event(
            type=Events.STATUS_UPDATE,
            data={"status": "running"},
            source="main"
        ))
    
    async def stop(self):
        """Stop all services."""
        if not self._running:
            return
        
        logger.info("Stopping services...")
        self._running = False
        
        # Stop sync engine
        try:
            await self.sync_engine.stop()
        except Exception as e:
            logger.error(f"Error stopping sync engine: {e}")
        
        # Stop peer link service
        try:
            await self.peer_link_service.stop()
        except Exception as e:
            logger.error(f"Error stopping peer link service: {e}")
        
        # Stop discovery service
        try:
            await self.discovery_service.stop()
        except Exception as e:
            logger.error(f"Error stopping discovery service: {e}")
        
        # Stop Reticulum service
        try:
            await self.reticulum_service.stop()
        except Exception as e:
            logger.error(f"Error stopping Reticulum service: {e}")
        
        # Stop container
        try:
            await self.container_manager.stop()
        except Exception as e:
            logger.error(f"Error stopping container: {e}")
        
        # Stop UI
        try:
            self.launcher.stop()
        except Exception as e:
            logger.error(f"Error stopping launcher: {e}")
        
        logger.info("All services stopped!")
        
        # Exit
        sys.exit(0)
    
    def run(self):
        """Run the application."""
        # Create event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Start services
        loop.run_until_complete(self.start())
        
        # Start UI (this blocks)
        try:
            self.launcher.start()
        except KeyboardInterrupt:
            pass
        
        # Stop services
        loop.run_until_complete(self.stop())
        loop.close()


def main():
    """Main entry point."""
    app = PersonalCloudOS()
    app.run()


if __name__ == "__main__":
    main()
