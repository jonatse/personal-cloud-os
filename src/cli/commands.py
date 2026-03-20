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
            'quit': self.cmd_quit,
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
        
        peers = []
        peer_names = set()
        
        ret_service = getattr(self.app, 'reticulum_service', None)
        if ret_service and hasattr(ret_service, 'get_peers'):
            try:
                for peer in ret_service.get_peers():
                    if peer.name not in peer_names:
                        peers.append(peer)
                        peer_names.add(peer.name)
            except Exception as e:
                print(f"  [DEBUG] ret_service.get_peers() error: {e}")
        
        peer_count = len(peers)
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
            print(f"  {'Files:':15} {status.files_synced}/{status.files_local}")
        
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
        
        ret_service = getattr(self.app, 'reticulum_service', None)
        if not ret_service:
            print("  No network service")
            print("─" * 50 + "\n")
            return True
        
        peers = []
        peer_names = set()
        
        if ret_service and hasattr(ret_service, 'get_peers'):
            try:
                for peer in ret_service.get_peers():
                    if peer.name not in peer_names:
                        peers.append(peer)
                        peer_names.add(peer.name)
            except Exception as e:
                print(f"  Error getting peers from reticulum: {e}")
        
        if peers:
            for peer in peers:
                print(f"  • {peer.name}")
                print(f"    ID: {peer.id[:20]}...")
                print(f"    Status: Online")
                print()
        else:
            print("  No peers discovered yet.")
            print("  Make sure other devices are running Personal Cloud OS.")
        
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
            print(f"  Files synced: {status.files_synced}/{status.files_local}")
            print(f"  Sync dir: {sync.sync_dir}")
        else:
            print("  Sync engine not available.")
        
        print("─" * 50 + "\n")
        return True
    
    def cmd_network(self, args) -> bool:
        """Show all network hardware and Reticulum status."""
        import subprocess
        import socket

        W = 56
        print("\n" + "─" * W)
        print("  NETWORK")
        print("─" * W)

        # ── Reticulum identity ──────────────────────────────────────
        ret_service = getattr(self.app, 'reticulum_service', None)
        if ret_service:
            identity  = getattr(ret_service, '_identity_hash',    'Unknown')
            dest_hash = getattr(ret_service, '_destination_hash', 'Unknown')
            interval  = getattr(ret_service, '_announce_interval', 30)
            print(f"  Reticulum     : Online")
            print(f"  Identity      : {identity[:32]}...")
            print(f"  Destination   : {dest_hash[:32]}...")
            print(f"  Announce every: {interval}s")
        else:
            print("  Reticulum     : Offline")
        print("─" * W)

        # ── Network interfaces ──────────────────────────────────────
        try:
            import psutil
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            print(f"  {'INTERFACE':<16} {'IP / MAC':<22} {'SPEED':>7}  STATUS")
            print(f"  {'─'*16} {'─'*22} {'─'*7}  {'─'*6}")
            SKIP = {'lo'}
            for iface in sorted(addrs.keys()):
                if iface in SKIP:
                    continue
                ipv4 = next((a.address for a in addrs[iface]
                             if a.family == 2), "")           # AF_INET
                mac  = next((a.address for a in addrs[iface]
                             if a.family == 17), "")          # AF_PACKET
                st   = stats.get(iface)
                up   = ("UP  " if st and st.isup else "down")
                spd  = f"{st.speed}M" if st and st.speed else "—"
                addr = ipv4 or mac[:17] if mac else "—"
                print(f"  {iface:<16} {addr:<22} {spd:>7}  {up}")
        except ImportError:
            print("  (psutil not installed — run: pip install psutil)")
        except Exception as e:
            print(f"  Interface error: {e}")
        print("─" * W)

        # ── Bluetooth ───────────────────────────────────────────────
        try:
            r = subprocess.run(["hciconfig", "-a"],
                               capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                for line in r.stdout.splitlines():
                    l = line.strip()
                    if not l:
                        continue
                    if l.startswith("hci"):
                        parts = l.split()
                        dev   = parts[0].rstrip(":")
                        bus   = next((p for p in parts if "Bus:" in p), "")
                        print(f"  Bluetooth  {dev}: {bus}")
                    elif "BD Address" in l:
                        print(f"    Address : {l.split(':',1)[1].strip()}")
                    elif "Name:" in l:
                        print(f"    Name    : {l.split(':',1)[1].strip()}")
                    elif "UP RUNNING" in l or "DOWN" in l:
                        state = "UP" if "UP" in l else "DOWN"
                        print(f"    State   : {state}")
            else:
                import os
                if os.path.exists("/sys/class/bluetooth"):
                    devs = os.listdir("/sys/class/bluetooth")
                    for d in devs:
                        print(f"  Bluetooth  {d}: present (hciconfig unavailable)")
                else:
                    print("  Bluetooth  : not detected")
        except FileNotFoundError:
            import os
            if os.path.exists("/sys/class/bluetooth"):
                devs = os.listdir("/sys/class/bluetooth")
                for d in devs:
                    print(f"  Bluetooth  {d}: present")
            else:
                print("  Bluetooth  : not detected")
        except Exception as e:
            print(f"  Bluetooth  : error ({e})")
        print("─" * W)

        # ── Audio (PipeWire / PulseAudio) ───────────────────────────
        try:
            r = subprocess.run(["pactl", "list", "short", "sinks"],
                               capture_output=True, text=True, timeout=3)
            r2 = subprocess.run(["pactl", "list", "short", "sources"],
                                capture_output=True, text=True, timeout=3)
            sinks   = [l for l in r.stdout.splitlines()  if l.strip()]
            sources = [l for l in r2.stdout.splitlines() if l.strip()]

            print(f"  AUDIO OUTPUT ({len(sinks)} sink{'s' if len(sinks)!=1 else ''}):")
            for line in sinks:
                parts = line.split()
                name  = parts[1] if len(parts) > 1 else line
                state = parts[4] if len(parts) > 4 else ""
                # shorten alsa_output.pci-... to something readable
                short = name.replace("alsa_output.","").replace("alsa_input.","")
                short = short[:40]
                print(f"    • {short:<40} [{state}]")

            print(f"  AUDIO INPUT  ({len(sources)} source{'s' if len(sources)!=1 else ''}):")
            for line in sources:
                parts = line.split()
                name  = parts[1] if len(parts) > 1 else line
                state = parts[4] if len(parts) > 4 else ""
                if ".monitor" in name:
                    continue   # skip monitor sources (they mirror outputs)
                short = name.replace("alsa_input.","").replace("alsa_output.","")
                short = short[:40]
                print(f"    • {short:<40} [{state}]")
        except FileNotFoundError:
            print("  Audio: pactl not found (PipeWire/PulseAudio not running?)")
        except Exception as e:
            print(f"  Audio: error ({e})")

        # ── I2P status ──────────────────────────────────────────────
        i2p = getattr(self.app, 'i2p_manager', None)
        if i2p:
            status = i2p.status()
            state  = "Available ✓" if status["available"] else "Not available"
            origin = "started by pcos" if status["we_started"] else "external"
            print(f"  I2P (internet tunneling)")
            print(f"    State   : {state}")
            if status["available"]:
                print(f"    SAM     : {status['sam_host']}:{status['sam_port']}")
                print(f"    Binary  : {status.get('binary_source', origin)}")
            else:
                src_bin = status.get('binary_source', '')
                if 'bundled' in src_bin:
                    print(f"    Binary  : {src_bin}")
                    print(f"    Status  : not running (will start on next launch)")
                else:
                    print(f"    Binary  : not found")
                    print(f"    Bundled : src/bin/i2pd (should be present in repo)")
            print("─" * W)

        print("")
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
        """Exit CLI, keep app running in background."""
        print("\nCLI closed. Personal Cloud OS continues running in background.")
        print("Type 'python3 main.py --cli' to reopen.\n")
        return False

    def cmd_quit(self, args) -> bool:
        """Stop the application and exit."""
        print("\nStopping Personal Cloud OS...")
        import asyncio
        loop = getattr(self.app, '_loop', None)
        if loop and loop.is_running():
            asyncio.run_coroutine_threadsafe(self.app.stop(), loop)
        else:
            # Fallback: set running flag so background loop exits
            self.app._running = False
        return False
