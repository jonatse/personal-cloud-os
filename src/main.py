"""Personal Cloud OS - Main Entry Point."""
import asyncio
import logging
import signal
import sys
import os
import argparse

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.config import Config
from core.events import Event, Events, event_bus
from core.logger import setup_logging, get_logger
from core.device_manager import DeviceManager
from services.reticulum_peer import ReticulumPeerService
from services.discovery import PeerDiscoveryService
from services.peer_link import PeerLinkService
from services.sync import SyncEngine
from container.manager import ContainerManager
from cli.interface import CLIInterface


logger = get_logger(__name__)


class PersonalCloudOS:
    """
    Main application class that orchestrates all services.
    
    Runs as a background service with CLI management interface.
    """
    
    def __init__(self, cli_mode=False):
        """Initialize the application."""
        # Load configuration
        self.config = Config()
        
        # Setup logging
        setup_logging(
            level="DEBUG" if self.config.get("app.debug") else "INFO",
            log_file=os.path.expanduser("~/.local/share/pcos/logs/app.log")
        )
        
        # Initialize device manager - fingerprints this device and registers in inventory
        self.device_manager = DeviceManager()
        self.device_manager.register_self()
        
        # CLI mode flag
        self.cli_mode = cli_mode
        
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
        
        if self.cli_mode:
            # CLI mode - run interactive CLI
            cli = CLIInterface(self)
            try:
                cli.start()
            except KeyboardInterrupt:
                pass
        else:
            # Background mode - just wait
            logger.info("Running in background. Use CLI to manage.")
            logger.info("  python main.py --cli    # Open CLI")
            logger.info("  python main.py --status # Show status and exit")
            
            try:
                while self._running:
                    signal.pause()
            except KeyboardInterrupt:
                pass
        
        # Stop services
        loop.run_until_complete(self.stop())
        loop.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Personal Cloud OS')
    parser.add_argument('--cli', action='store_true', help='Open CLI interface')
    parser.add_argument('--tray', action='store_true', help='Run with system tray')
    parser.add_argument('--status', action='store_true', help='Show status and exit')
    parser.add_argument('--start', action='store_true', help='Start services and run in background')
    parser.add_argument('--stop', action='store_true', help='Stop running services')
    
    args = parser.parse_args()
    
    if args.status:
        # Just show status
        print("Checking Personal Cloud OS status...")
        print("Run with --start to start the service")
        return
    
    if args.tray:
        # Run with system tray
        try:
            from tray.system_tray import SystemTray
            app = PersonalCloudOS()
            tray = SystemTray(app)
            tray.start()
            app.run()
        except ImportError as e:
            print(f"System tray not available: {e}")
            print("Falling back to background mode...")
            app = PersonalCloudOS()
            app.run()
        return
    
    app = PersonalCloudOS(cli_mode=args.cli)
    app.run()


if __name__ == "__main__":
    main()
