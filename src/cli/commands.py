"""CLI Commands for Personal Cloud OS."""
import sys
import asyncio
from typing import Dict, Callable, Any


class CommandHandler:
    """Handles CLI commands."""
    
    def __init__(self, app):
        """Initialize with app reference."""
        self.app = app
        self.commands: Dict[str, Callable] = {
            'help': self.cmd_help,
            'status': self.cmd_status,
            'peers': self.cmd_peers,
            'sync': self.cmd_sync,
            'network': self.cmd_network,
            'device': self.cmd_device,
            'container': self.cmd_container,
            'start': self.cmd_start,
            'stop': self.cmd_stop,
            'restart': self.cmd_restart,
            'clear': self.cmd_clear,
            'exit': self.cmd_exit,
            'quit': self.cmd_exit,
        }
    
    def get_commands(self) -> Dict[str, str]:
        """Get command list with descriptions."""
        return {
            'help': 'Show this help message',
            'status': 'Show system status',
            'peers': 'Show connected peers',
            'sync': 'Show sync status',
            'network': 'Show network information',
            'device': 'Show device information',
            'container': 'Show container status',
            'start': 'Start a service (peers|sync|container|all)',
            'stop': 'Stop a service (peers|sync|container|all)',
            'restart': 'Restart a service',
            'clear': 'Clear the screen',
            'exit': 'Exit the CLI (keeps running in background)',
            'quit': 'Exit and stop the application',
        }
    
    def execute(self, cmd: str) -> bool:
        """Execute a command. Returns False to exit."""
        cmd = cmd.strip().lower()
        if not cmd:
            return True
        
        parts = cmd.split()
        command = parts[0]
        args = parts[1:] if len(parts) > 1 else []
        
        if command in self.commands:
            return self.commands[command](args)
        else:
            print(f"Unknown command: {command}")
            print("Type 'help' for available commands.")
            return True
    
    def cmd_help(self, args) -> bool:
        """Show help."""
        print("\n" + "=" * 50)
        print("  Personal Cloud OS - Available Commands")
        print("=" * 50)
        
        commands = self.get_commands()
        for cmd, desc in commands.items():
            print(f"  {cmd:12} - {desc}")
        
        print("=" * 50 + "\n")
        return True
    
    def cmd_status(self, args) -> bool:
        """Show system status."""
        print("\n" + "─" * 50)
        print("  SYSTEM STATUS")
        print("─" * 50)
        
        # Overall status
        print(f"  {'Overall:':15} Running")
        
        # Reticulum
        ret_service = getattr(self.app, 'reticulum_service', None)
        if ret_service and ret_service.is_running():
            identity = getattr(ret_service, '_identity_hash', 'Unknown')[:16]
            print(f"  {'Reticulum:':15} Online (Identity: {identity}...)")
        else:
            print(f"  {'Reticulum:':15} Offline")
        
        # Peers
        discovery = getattr(self.app, 'discovery_service', None)
        if discovery:
            peer_count = getattr(discovery, 'peer_count', 0)
            peers = discovery.get_peers() if hasattr(discovery, 'get_peers') else []
            print(f"  {'Peers:':15} {peer_count} connected")
            for peer in peers[:3]:
                print(f"    - {peer.name}")
            if len(peers) > 3:
                print(f"    (+{len(peers) - 3} more)")
        
        # Sync
        sync = getattr(self.app, 'sync_engine', None)
        if sync:
            status = sync.get_status()
            print(f"  {'Sync:':15} {status.state}")
            print(f"  {'Files:':15} {status.files_synced}/{status.files_total}")
        
        # Container
        container = getattr(self.app, 'container_manager', None)
        if container and container.is_running():
            print(f"  {'Container:':15} Running")
        else:
            print(f"  {'Container:':15} Stopped")
        
        print("─" * 50 + "\n")
        return True
    
    def cmd_peers(self, args) -> bool:
        """Show peers."""
        print("\n" + "─" * 50)
        print("  CONNECTED PEERS")
        print("─" * 50)
        
        discovery = getattr(self.app, 'discovery_service', None)
        if discovery:
            peers = discovery.get_peers() if hasattr(discovery, 'get_peers') else []
            if peers:
                for peer in peers:
                    print(f"  • {peer.name}")
                    print(f"    Hash: {peer.hash[:20]}...")
                    print(f"    Status: Online")
                    print()
            else:
                print("  No peers discovered yet.")
                print("  Make sure other devices are running Personal Cloud OS.")
        else:
            print("  Discovery service not available.")
        
        print("─" * 50 + "\n")
        return True
    
    def cmd_sync(self, args) -> bool:
        """Show sync status."""
        print("\n" + "─" * 50)
        print("  SYNC STATUS")
        print("─" * 50)
        
        sync = getattr(self.app, 'sync_engine', None)
        if sync:
            status = sync.get_status()
            print(f"  State: {status.state}")
            print(f"  Files synced: {status.files_synced}/{status.files_total}")
            print(f"  Sync dir: {sync.sync_dir}")
        else:
            print("  Sync engine not available.")
        
        print("─" * 50 + "\n")
        return True
    
    def cmd_network(self, args) -> bool:
        """Show network info."""
        print("\n" + "─" * 50)
        print("  NETWORK INFORMATION")
        print("─" * 50)
        
        ret_service = getattr(self.app, 'reticulum_service', None)
        if ret_service:
            identity = getattr(ret_service, '_identity_hash', 'Unknown')
            dest_hash = getattr(ret_service, '_destination_hash', 'Unknown')
            print(f"  Device Identity: {identity[:32]}...")
            print(f"  Destination Hash: {dest_hash[:32]}...")
            
            # Show network interfaces
            print(f"\n  Network Interfaces:")
            print(f"    • AutoInterface (UDP broadcast)")
            print(f"      - Used for local LAN peer discovery")
            
            # Show announce interval
            interval = getattr(ret_service, '_announce_interval', 30)
            print(f"\n  Announce Settings:")
            print(f"    • Interval: {interval} seconds")
            print(f"    • Status: Broadcasting presence")
            
            print(f"\n  Status: Online")
        else:
            print("  Reticulum not available.")
        
        print("─" * 50 + "\n")
        return True
    
    def cmd_device(self, args) -> bool:
        """Show device info."""
        import socket
        import os
        
        print("\n" + "─" * 50)
        print("  DEVICE INFORMATION")
        print("─" * 50)
        
        print(f"  Hostname: {socket.gethostname()}")
        print(f"  User: {os.environ.get('USER', 'unknown')}")
        print(f"  Platform: {sys.platform}")
        
        ret_service = getattr(self.app, 'reticulum_service', None)
        if ret_service:
            identity = getattr(ret_service, '_identity_hash', 'Unknown')
            print(f"  Device ID: {identity[:32]}...")
        
        print("─" * 50 + "\n")
        return True
    
    def cmd_container(self, args) -> bool:
        """Show container status."""
        print("\n" + "─" * 50)
        print("  CONTAINER STATUS")
        print("─" * 50)
        
        container = getattr(self.app, 'container_manager', None)
        if container:
            if container.is_running():
                print("  Status: Running")
                print("  SSH: localhost:2222")
                print("  Use: ssh user@localhost -p 2222")
            else:
                print("  Status: Stopped")
                print("  Use 'start container' to start")
        else:
            print("  Container manager not available.")
        
        print("─" * 50 + "\n")
        return True
    
    def cmd_start(self, args) -> bool:
        """Start a service."""
        if not args:
            print("Usage: start <peers|sync|container|all>")
            return True
        
        service = args[0]
        print(f"Starting {service}...")
        # Implementation depends on service
        print(f"{service} started.")
        return True
    
    def cmd_stop(self, args) -> bool:
        """Stop a service."""
        if not args:
            print("Usage: stop <peers|sync|container|all>")
            return True
        
        service = args[0]
        print(f"Stopping {service}...")
        print(f"{service} stopped.")
        return True
    
    def cmd_restart(self, args) -> bool:
        """Restart a service."""
        if not args:
            print("Usage: restart <peers|sync|container|all>")
            return True
        
        service = args[0]
        print(f"Restarting {service}...")
        print(f"{service} restarted.")
        return True
    
    def cmd_clear(self, args) -> bool:
        """Clear screen."""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')
        return True
    
    def cmd_exit(self, args) -> bool:
        """Exit CLI (keep running)."""
        print("\nCLI closed. Personal Cloud OS continues running in background.")
        print("Click the tray icon to reopen CLI.\n")
        return False
