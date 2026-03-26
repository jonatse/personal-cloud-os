"""Personal Cloud OS - Main Entry Point."""
# ── Vendor path bootstrap ──────────────────────────────────────────────────
# Must happen before ANY other imports so vendored packages take priority
# over anything installed system-wide. This is what makes the app
# self-contained — no pip install required on the target machine.
import sys
import os

_SRC_DIR    = os.path.dirname(os.path.abspath(__file__))
_VENDOR_DIR = os.path.join(_SRC_DIR, 'vendor')

if os.path.isdir(_VENDOR_DIR) and _VENDOR_DIR not in sys.path:
    sys.path.insert(0, _VENDOR_DIR)

# Keep src/ itself on the path so our own modules resolve correctly
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
# ── End vendor bootstrap ───────────────────────────────────────────────────

# ── Startup self-check ─────────────────────────────────────────────────────
# Run verify.py silently at startup. Logs warnings/failures but never
# prevents the app from starting — the user can still run manually.
def _run_startup_verify():
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "verify",
            os.path.join(_SRC_DIR, "verify.py")
        )
        verify = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verify)
        report = verify.run_checks(quiet=True)
        if not report.success:
            print(f"\n[WARN] Startup checks failed — run 'python3 verify.py' for details")
    except Exception:
        pass   # verify.py missing or broken — not fatal

_run_startup_verify()
# ── End startup self-check ─────────────────────────────────────────────────

import asyncio
import logging
import signal
import argparse
import sys

from core.config import Config
from core.events import Event, Events, event_bus
from core.logger import setup_logging, get_logger
from core.device_manager import DeviceManager
from core.version import __version__, __app_name__
from services.reticulum_peer import ReticulumPeerService
from services.i2p_manager import I2PManager
from services.sync import SyncEngine
from services.socket_api import SocketAPI
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
        logger.info(f"Version: {__version__}")
        logger.info("=" * 60)
        
        # Initialize Reticulum peer service (core networking)
        self.reticulum_service = ReticulumPeerService(self.config, event_bus)

        # Initialize I2P manager (internet tunneling — gracefully skipped if i2pd not installed)
        self.i2p_manager = I2PManager(self.config)
        
        # Transport manager — link classification and WireGuard (future)
        from transport import TransportManager
        self.transport_manager = TransportManager(self.reticulum_service, event_bus)

        # Sync engine — uses RNS natively via reticulum_service
        self.sync_engine = SyncEngine(
            self.config,
            event_bus,
            self.reticulum_service,
            transport_manager=self.transport_manager,
        )
        
        # Initialize container manager
        self.container_manager = ContainerManager(self.config, event_bus)
        
        # Socket API for container control and diagnostics
        self.socket_api = SocketAPI(
            reticulum_service=None,  # Will be set after services start
            sync_service=None,
            event_bus=event_bus
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
        # Schedule stop() onto the running event loop from the signal handler
        # (signal handlers run in the main thread; the loop may be running there too)
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(
                lambda: self._loop.create_task(self._stop_and_exit())
            )

    async def _stop_and_exit(self):
        """Stop all services then stop the event loop."""
        await self.stop()
        self._loop.stop()
    
    async def start(self):
        """Start all services."""
        if self._running:
            logger.warning("Application already running")
            return
        
        logger.info("Starting services...")
        self._running = True
        
        # Start I2P first so Reticulum config is patched before RNS reads it
        try:
            await self.i2p_manager.start()
        except Exception as e:
            logger.error(f"Failed to start I2P manager: {e}")

        # Start Reticulum networking (foundation for everything)
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
        
        # Start sync engine
        try:
            await self.sync_engine.start()
        except Exception as e:
            logger.error(f"Failed to start sync engine: {e}")
        
        # Start socket API for control interface
        try:
            # Set the services after they've been created
            self.socket_api.reticulum_service = self.reticulum_service
            self.socket_api.sync_service = self.sync_engine
            await self.socket_api.start()
        except Exception as e:
            logger.error(f"Failed to start socket API: {e}")
        
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
        
        # Stop transport manager (tears down WireGuard tunnels, swarm)
        try:
            if hasattr(self, 'transport_manager'):
                self.transport_manager.stop()
        except Exception as e:
            logger.error(f"Error stopping transport manager: {e}")

        # Stop sync engine
        try:
            await self.sync_engine.stop()
        except Exception as e:
            logger.error(f"Error stopping sync engine: {e}")
        
        # Stop Reticulum service
        try:
            await self.reticulum_service.stop()
        except Exception as e:
            logger.error(f"Error stopping Reticulum service: {e}")

        # Stop I2P manager
        try:
            await self.i2p_manager.stop()
        except Exception as e:
            logger.error(f"Error stopping I2P manager: {e}")
        
        # Stop container
        try:
            await self.container_manager.stop()
        except Exception as e:
            logger.error(f"Error stopping container: {e}")
        
        # Stop socket API
        try:
            await self.socket_api.stop()
        except Exception as e:
            logger.error(f"Error stopping socket API: {e}")
        
        logger.info("All services stopped!")
    
    def run(self):
        """Run the application."""
        # Clear old logs if bigger than 1MB
        log_file = os.path.expanduser("~/.local/share/pcos/logs/app.log")
        if os.path.exists(log_file) and os.path.getsize(log_file) > 1024*1024:
            logger.info("Log file too large, truncating...")
            open(log_file, 'w').close()
        
        # Create event loop — exposed as self._loop so CLI quit can schedule stop()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        # Start services
        loop.run_until_complete(self.start())
        
        if self.cli_mode:
            # CLI mode - run interactive CLI on the main thread while the loop
            # keeps spinning in a background thread so RNS callbacks work.
            import threading
            loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
            loop_thread.start()
            cli = CLIInterface(self)
            self.cli_interface = cli  # Add this line so commands can access it
            try:
                cli.start()
            except KeyboardInterrupt:
                pass
            # Signal the loop to stop
            loop.call_soon_threadsafe(
                lambda: loop.create_task(self._stop_and_exit())
            )
            loop_thread.join(timeout=10)
        else:
            # Background mode — keep the event loop running so that coroutines
            # scheduled by RNS background threads (via run_coroutine_threadsafe)
            # are actually executed.
            logger.info("Running in background. Use CLI to manage.")
            logger.info("  python main.py --cli    # Open CLI")
            logger.info("  python main.py --status # Show status and exit")
            try:
                loop.run_forever()
            except KeyboardInterrupt:
                pass
            # run_forever() returned (either from signal handler or KeyboardInterrupt)
            loop.run_until_complete(self.stop())

        loop.close()


async def test_remote_command(peer_name: str, command: str):
    """Test remote command execution - called via --test-remote flag."""
    app = PersonalCloudOS()
    await app.start()
    
    # Wait for peers
    await asyncio.sleep(5)
    
    # Find peer
    ret_service = app.reticulum_service
    target_peer = None
    for peer in ret_service.get_peers():
        if peer.name == peer_name or peer_name in peer.id:
            target_peer = peer
            break
    
    if not target_peer:
        print(f"Peer '{peer_name}' not found")
        await app.stop()
        return
    
    print(f"Executing '{command}' on {target_peer.name}...")
    result = await ret_service.execute_command(target_peer.id, command)
    
    if result:
        print(f"Exit code: {result.get('exit_code')}")
        print(f"Output: {result.get('stdout')}")
        if result.get('stderr'):
            print(f"Error: {result.get('stderr')}")
    else:
        print("Command failed")
    
    await app.stop()


def main():
    """Main entry point."""
    
    if "--test-remote" in sys.argv:
        idx = sys.argv.index("--test-remote")
        if len(sys.argv) > idx + 2:
            peer = sys.argv[idx+1]
            cmd = sys.argv[idx+2]
            asyncio.run(test_remote_command(peer, cmd))
            return
    
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
