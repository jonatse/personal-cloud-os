"""CLI Commands for Personal Cloud OS."""
import sys
import asyncio
import json
import logging
import os
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
            'shell': self.cmd_shell,
            'start': self.cmd_start,
            'stop': self.cmd_stop,
            'restart': self.cmd_restart,
            'clear': self.cmd_clear,
            'exit': self.cmd_exit,
            'quit': self.cmd_quit,
            'identity': self.cmd_identity,
            'circle': self.cmd_circle,
            'contact': self.cmd_contact,
            'link': self.cmd_link,
            'logs': self.cmd_logs,
            'remote': self.cmd_remote,
        }
        self._identity_manager = None

    def _get_identity_manager(self):
        """Get or create identity manager."""
        if self._identity_manager is None:
            from core.identity import IdentityManager
            self._identity_manager = IdentityManager()
        return self._identity_manager

    def _socket_query(self, cmd: str, params: dict = None) -> dict:
        """Send a command to the socket API and return the response."""
        import socket
        import json
        
        socket_path = os.path.expanduser('~/.local/run/pcos/messaging.sock')
        if not os.path.exists(socket_path):
            return {'error': 'socket_not_available'}
        
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect(socket_path)
            request = {'cmd': cmd}
            if params:
                request.update(params)
            sock.send((json.dumps(request) + '\n').encode())
            response = sock.recv(8192)
            sock.close()
            return json.loads(response.decode()) if response else {'error': 'empty_response'}
        except socket.timeout:
            return {'error': 'timeout'}
        except Exception as e:
            return {'error': str(e)}
    
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
            'identity': 'Manage identity (create, show, export, import, show-qr)',
            'circle': 'Manage trust circles (create, list, add, remove)',
            'contact': 'Manage contacts (list, add, show, update, remove, search, ref, merge, export, import)',
            'link': 'Show link status and verify encryption',
            'logs': 'Show application logs (optional: --follow, --level LEVEL, lines)',
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
    
    def cmd_shell(self, args) -> bool:
        """Open interactive Alpine Linux shell."""
        import subprocess
        import socket
        import os
        import sys
        
        print("\n" + "─" * 50)
        print("  ALPINE LINUX SHELL")
        print("─" * 50)
        print("  Type 'exit' to return to PCOS CLI")
        print("─" * 50 + "\n")
        
        socket_path = os.path.expanduser("~/.local/run/pcos/container.sock")
        
        if not os.path.exists(socket_path):
            print("Container shell not available. Is PCOS running?")
            return True
        
        # Try to use xterm or any available terminal
        terminals = ['xterm', 'gnome-terminal', 'konsole', 'xfce4-terminal', 'lxterminal', 'kitty']
        terminal = None
        for t in terminals:
            if subprocess.run(['which', t], capture_output=True).returncode == 0:
                terminal = t
                break
        
        if not terminal:
            # Fallback: use script command for pseudo-terminal
            try:
                # Use 'script' to give us a PTY
                proc = subprocess.Popen(
                    ['script', '-q', '-c', f'nc -U {socket_path}', '/dev/null'],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT
                )
                # Relay input/output
                import select
                while True:
                    r, _, _ = select.select([sys.stdin, proc.stdout], [], [], 0.1)
                    if sys.stdin in r:
                        data = sys.stdin.read(1)
                        if not data:
                            break
                        proc.stdin.write(data.encode())
                        proc.stdin.flush()
                    if proc.stdout in r:
                        sys.stdout.write(proc.stdout.read(1))
                        sys.stdout.flush()
                proc.terminate()
            except Exception as e:
                print(f"Could not open shell: {e}")
                print("Alternative: run 'nc -U ~/.local/run/pcos/container.sock' in terminal")
        else:
            # Open terminal connected to shell socket
            if terminal == 'xterm':
                subprocess.run([terminal, '-e', f'socat - UNIX-CONNECT:{socket_path}'])
            elif terminal == 'gnome-terminal':
                subprocess.run([terminal, '--', 'bash', '-c', f'socat - UNIX-CONNECT:{socket_path}'])
            elif terminal == 'kitty':
                subprocess.run([terminal, '@', 'pipe', '--', f'nc -U {socket_path}'])
            else:
                subprocess.run([terminal, '-e', f'socat - UNIX-CONNECT:{socket_path}'])
        
        return True
    
    def cmd_start(self, args) -> bool:
        """Start a service."""
        if not args:
            print("Usage: start <peers|sync|container|i2p|all>")
            return True
        
        import asyncio
        service = args[0]
        valid_services = ['peers', 'sync', 'container', 'i2p', 'all']
        
        if service not in valid_services:
            print(f"Unknown service: {service}. Valid: {valid_services}")
            return True
        
        async def do_start():
            services_to_start = []
            if service == 'all':
                services_to_start = ['peers', 'sync', 'container', 'i2p']
            else:
                services_to_start = [service]
            
            for svc in services_to_start:
                if svc == 'peers':
                    await self.app.reticulum_service.start()
                elif svc == 'sync':
                    await self.app.sync_engine.start()
                elif svc == 'container':
                    await self.app.container_manager.start()
                elif svc == 'i2p':
                    await self.app.i2p_manager.start()
        
        try:
            asyncio.run(do_start())
            print(f"✓ {service} started")
        except Exception as e:
            print(f"✗ Failed to start {service}: {e}")
        
        return True
    
    def cmd_stop(self, args) -> bool:
        """Stop a service via socket API."""
        if not args:
            print("Usage: stop <peers|sync|container|i2p|all>")
            return True
        
        service = args[0]
        valid_services = ['peers', 'sync', 'container', 'i2p', 'all']
        
        if service not in valid_services:
            print(f"Unknown service: {service}. Valid: {valid_services}")
            return True
        
        resp = self._socket_query('service_stop', {'service': service})
        
        if 'error' in resp:
            print(f"✗ Failed to stop {service}: {resp['error']}")
        else:
            print(f"✓ {service} stopped")
        
        return True
    
    def cmd_restart(self, args) -> bool:
        """Restart a service via socket API."""
        if not args:
            print("Usage: restart <peers|sync|container|i2p|all>")
            return True
        
        service = args[0]
        valid_services = ['peers', 'sync', 'container', 'i2p', 'all']
        
        if service not in valid_services:
            print(f"Unknown service: {service}. Valid: {valid_services}")
            return True
        
        resp = self._socket_query('service_restart', {'service': service})
        
        if 'error' in resp:
            print(f"✗ Failed to restart {service}: {resp['error']}")
        else:
            print(f"✓ {service} restarted")
        
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
        
        loop = getattr(self.app, '_loop', None)
        if loop and loop.is_running():
            # Schedule the stop on the event loop
            # call_soon_threadsafe is safe to call from any thread
            async def stop_app():
                await self.app.stop()
            
            # Create a callback that runs the coroutine in the event loop
            def run_stop():
                if loop.is_running():
                    asyncio.run_coroutine_threadsafe(stop_app(), loop).result()
            
            loop.call_soon_threadsafe(run_stop)
            
            # Also stop the CLI interface so it exits
            cli_interface = getattr(self.app, 'cli_interface', None)
            if cli_interface:
                cli_interface.stop()
        else:
            # Fallback: set running flag so background loop exits
            self.app._running = False
        
        return False

    def cmd_identity(self, args) -> bool:
        """Manage identity."""
        import logging
        import os

        logger = logging.getLogger(__name__)
        subcommand = args[0] if args else 'show'

        if subcommand in ('show', ''):
            # Use socket API
            resp = self._socket_query('identity')
            if 'error' in resp:
                print(f"Error: {resp['error']}")
            else:
                print("\n" + "─" * 50)
                print("  IDENTITY")
                print("─" * 50)
                print(f"  Hash: {resp.get('hash', 'unknown')}")
                print(f"  Path: {resp.get('path', 'unknown')}")
                print(f"  Trust Level: {resp.get('trust_level', 'unknown')}")
                print("─" * 50 + "\n")
            return True

        if subcommand == 'create':
            # Use socket API
            resp = self._socket_query('identity', {'subcommand': 'create'})
            if 'error' in resp:
                print(f"Error: {resp['error']}")
                if 'identity_exists' in resp.get('error', ''):
                    print(resp.get('message', ''))
            else:
                print(f"Identity created successfully!")
                print(f"Hash: {resp.get('hash', 'unknown')}")
                logger.info(f"Created new identity")
            return True

        if subcommand == 'export':
            try:
                id_mgr.load_or_create_identity()
                exported = id_mgr.export_identity()
                print("\n" + "─" * 50)
                print("  IDENTITY EXPORT")
                print("─" * 50)
                print(exported)
                print("─" * 50 + "\n")
                return True
            except Exception as e:
                print(f"Error exporting identity: {e}")
                logger.error(f"Error exporting identity: {e}")
                return True

        if subcommand == 'import':
            if len(args) < 2:
                print("Usage: identity import <base64>")
                return True
            try:
                base64_str = args[1]
                identity = id_mgr.import_identity(base64_str)
                print(f"Identity imported successfully!")
                print(f"Hash: {identity.hash.hex()[:32]}...")
                logger.info(f"Imported identity: {identity.hash.hex()[:16]}...")
                return True
            except Exception as e:
                print(f"Error importing identity: {e}")
                logger.error(f"Error importing identity: {e}")
                return True

        if subcommand == 'show-qr':
            try:
                import qrcode
                id_mgr.load_or_create_identity()
                exported = id_mgr.export_identity()
                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(exported)
                qr.make(fit=True)
                qr.print_ascii()
                print("\nScan this QR code to import identity.")
                return True
            except ImportError:
                print("qrcode module not available.")
                print("Install it with: pip install qrcode")
                logger.warning("qrcode module not available for identity show-qr")
                return True
            except Exception as e:
                print(f"Error showing QR: {e}")
                logger.error(f"Error showing QR: {e}")
                return True

        if subcommand == 'import-qr':
            print("Paste the base64 identity string below (press Enter twice to confirm):")
            lines = []
            while True:
                try:
                    line = input()
                    if line == '':
                        break
                    lines.append(line)
                except EOFError:
                    break

            if not lines:
                print("No input received.")
                return True

            try:
                base64_str = ''.join(lines).strip()
                identity = id_mgr.import_identity(base64_str)
                print(f"Identity imported successfully!")
                print(f"Hash: {identity.hash.hex()[:32]}...")
                logger.info(f"Imported identity via QR: {identity.hash.hex()[:16]}...")
                return True
            except Exception as e:
                print(f"Error importing identity: {e}")
                logger.error(f"Error importing identity: {e}")
                return True

        print(f"Unknown subcommand: {subcommand}")
        print("Usage: identity <show|create|export|import|show-qr|import-qr>")
        return True

    def cmd_circle(self, args) -> bool:
        """Manage trust circles."""
        import logging

        logger = logging.getLogger(__name__)
        id_mgr = self._get_identity_manager()

        subcommand = args[0] if args else 'list'

        if subcommand in ('list', ''):
            try:
                circles = id_mgr.list_circles()
                print("\n" + "─" * 50)
                print("  TRUST CIRCLES")
                print("─" * 50)
                if circles:
                    for circle in circles:
                        print(f"  • {circle}")
                else:
                    print("  No circles found.")
                    print("  Use 'circle create <name>' to create one.")
                print("─" * 50 + "\n")
                return True
            except Exception as e:
                print(f"Error listing circles: {e}")
                logger.error(f"Error listing circles: {e}")
                return True

        if subcommand == 'create':
            if len(args) < 2:
                print("Usage: circle create <name>")
                return True
            try:
                name = args[1]
                circle_identity = id_mgr.create_circle(name)
                print(f"Circle '{name}' created successfully!")
                print(f"Identity: {circle_identity.hash.hex()[:32]}...")
                logger.info(f"Created circle: {name}")
                return True
            except Exception as e:
                print(f"Error creating circle: {e}")
                logger.error(f"Error creating circle: {e}")
                return True

        if subcommand == 'show':
            if len(args) < 2:
                print("Usage: circle show <name>")
                return True
            try:
                name = args[1]
                circle_identity = id_mgr.get_circle(name)
                if not circle_identity:
                    print(f"Circle '{name}' not found.")
                    return True

                members_file = os.path.join(id_mgr._circles_dir, name, "members.json")
                members = []
                if os.path.exists(members_file):
                    import json
                    with open(members_file, "r") as f:
                        members = json.load(f)

                print("\n" + "─" * 50)
                print(f"  CIRCLE: {name}")
                print("─" * 50)
                print(f"  Identity: {circle_identity.hash.hex()[:32]}...")
                print(f"  Members: {len(members)}")
                for member in members:
                    print(f"    - {member[:32]}...")
                print("─" * 50 + "\n")
                return True
            except Exception as e:
                print(f"Error showing circle: {e}")
                logger.error(f"Error showing circle: {e}")
                return True

        if subcommand == 'add':
            if len(args) < 3:
                print("Usage: circle add <name> <identity_base64>")
                return True
            try:
                name = args[1]
                identity_base64 = args[2]
                success = id_mgr.add_to_circle(name, identity_base64)
                if success:
                    print(f"Identity added to circle '{name}'.")
                    logger.info(f"Added identity to circle: {name}")
                else:
                    print(f"Failed to add identity to circle '{name}'.")
                return True
            except Exception as e:
                print(f"Error adding to circle: {e}")
                logger.error(f"Error adding to circle: {e}")
                return True

        if subcommand == 'remove':
            if len(args) < 3:
                print("Usage: circle remove <name> <identity_hash>")
                return True
            try:
                name = args[1]
                identity_hash = args[2]
                success = id_mgr.remove_from_circle(name, identity_hash)
                if success:
                    print(f"Identity removed from circle '{name}'.")
                    logger.info(f"Removed identity from circle: {name}")
                else:
                    print(f"Failed to remove identity from circle '{name}'.")
                return True
            except Exception as e:
                print(f"Error removing from circle: {e}")
                logger.error(f"Error removing from circle: {e}")
                return True

        print(f"Unknown subcommand: {subcommand}")
        print("Usage: circle <list|create|show|add|remove>")
        return True

    def cmd_contact(self, args) -> bool:
        """Manage contacts."""
        import logging
        import json

        logger = logging.getLogger(__name__)

        try:
            from core.contact_registry import ContactRegistry
            from core.identity import IdentityManager
            from core.device_manager import DeviceManager
        except ImportError as e:
            print(f"Error importing contact modules: {e}")
            return True

        subcommand = args[0] if args else 'list'

        # Initialize contact registry
        try:
            id_mgr = IdentityManager()
            id_mgr.load_or_create_identity()
            dev_mgr = DeviceManager()
            contact_reg = ContactRegistry(
                identity_manager=id_mgr,
                device_manager=dev_mgr,
            )
        except Exception as e:
            print(f"Error initializing contact registry: {e}")
            logger.error(f"Contact registry init error: {e}")
            return True

        if subcommand == 'list':
            filter_level = args[1] if len(args) > 1 else None
            contacts = contact_reg.list_contacts(trust_level=filter_level)
            print("\n" + "─" * 60)
            print("  CONTACTS")
            print("─" * 60)
            if contacts:
                for c in contacts:
                    name = c.get('display_name', 'Unknown')
                    trust = c.get('trust_level', 'unknown')
                    devices = len(c.get('devices', []))
                    device_str = f"{devices} device{'s' if devices != 1 else ''}"
                    print(f"  • {name}")
                    print(f"    Trust: {trust} | {device_str} | ID: {c['id'][:12]}...")
            else:
                print("  No contacts found.")
                print("  Use 'contact add <identity_hash> <name>' to add one.")
            print("─" * 60 + "\n")
            return True

        if subcommand == 'add':
            if len(args) < 3:
                print("Usage: contact add <identity_hash> <display_name> [phone_number]")
                return True
            identity_hash = args[1]
            display_name = args[2]
            phone_number = args[3] if len(args) > 3 else None
            try:
                contact = contact_reg.add_contact(
                    identity_hash=identity_hash,
                    display_name=display_name,
                    phone_number=phone_number,
                )
                print(f"Contact '{display_name}' added successfully!")
                print(f"  ID: {contact['id']}")
                print(f"  Identity: {identity_hash[:32]}...")
                print(f"  Trust level: {contact['trust_level']}")
                return True
            except Exception as e:
                print(f"Error adding contact: {e}")
                logger.error(f"Error adding contact: {e}")
                return True

        if subcommand == 'show':
            if len(args) < 2:
                print("Usage: contact show <contact_id|identity_hash>")
                return True
            query = args[1]
            # Try as contact ID first, then as identity hash
            contact = contact_reg.get_contact(query)
            if contact is None:
                contact = contact_reg.get_contact_by_identity(query)
            if contact is None:
                print(f"Contact not found: {query}")
                return True

            print("\n" + "─" * 60)
            print(f"  CONTACT: {contact.get('display_name', 'Unknown')}")
            print("─" * 60)
            print(f"  ID:            {contact['id']}")
            print(f"  Identity:      {contact['identity_hash'][:48]}...")
            print(f"  Trust level:   {contact['trust_level']}")
            if contact.get('phone_number'):
                print(f"  Phone:         {contact['phone_number']}")
            if contact.get('notes'):
                print(f"  Notes:         {contact['notes']}")
            print(f"  Created:       {contact['created_at']}")
            print(f"  Updated:       {contact['updated_at']}")

            devices = contact.get('devices', [])
            print(f"  Devices:       {len(devices)}")
            for dev in devices:
                print(f"    - {dev.get('hostname', 'unknown')} ({dev.get('device_id', '?')[:12]}...)")
                print(f"      Last seen: {dev.get('last_seen', 'never')}")

            refs = contact.get('refs', {})
            if refs:
                print(f"  Cross-references:")
                for ref_type, ref_ids in refs.items():
                    print(f"    {ref_type}: {len(ref_ids)} reference(s)")
            print("─" * 60 + "\n")
            return True

        if subcommand == 'update':
            if len(args) < 3:
                print("Usage: contact update <contact_id> <field=value> [field=value ...]")
                return True
            contact_id = args[1]
            contact = contact_reg.get_contact(contact_id)
            if contact is None:
                print(f"Contact not found: {contact_id}")
                return True

            updates = {}
            for arg in args[2:]:
                if '=' not in arg:
                    print(f"Invalid field format: {arg} (use field=value)")
                    return True
                key, value = arg.split('=', 1)
                updates[key] = value

            try:
                updated = contact_reg.update_contact(contact_id, **updates)
                print(f"Contact '{updated['display_name']}' updated.")
                for key, value in updates.items():
                    print(f"  {key}: {value}")
                return True
            except Exception as e:
                print(f"Error updating contact: {e}")
                logger.error(f"Error updating contact: {e}")
                return True

        if subcommand == 'remove':
            if len(args) < 2:
                print("Usage: contact remove <contact_id>")
                return True
            contact_id = args[1]
            contact = contact_reg.get_contact(contact_id)
            if contact is None:
                print(f"Contact not found: {contact_id}")
                return True

            try:
                contact_reg.remove_contact(contact_id)
                print(f"Contact '{contact.get('display_name', contact_id)}' removed.")
                return True
            except Exception as e:
                print(f"Error removing contact: {e}")
                logger.error(f"Error removing contact: {e}")
                return True

        if subcommand == 'search':
            if len(args) < 2:
                print("Usage: contact search <query>")
                return True
            query = ' '.join(args[1:])
            results = contact_reg.search_contacts(query)
            print("\n" + "─" * 60)
            print(f"  SEARCH RESULTS: '{query}'")
            print("─" * 60)
            if results:
                for c in results:
                    name = c.get('display_name', 'Unknown')
                    trust = c.get('trust_level', 'unknown')
                    print(f"  • {name} ({trust})")
                    if c.get('phone_number'):
                        print(f"    Phone: {c['phone_number']}")
                    if c.get('notes'):
                        print(f"    Notes: {c['notes'][:60]}...")
            else:
                print("  No contacts found matching query.")
            print("─" * 60 + "\n")
            return True

        if subcommand == 'ref':
            ref_action = args[1] if len(args) > 1 else 'list'
            if ref_action == 'add':
                if len(args) < 5:
                    print("Usage: contact ref add <contact_id> <ref_type> <ref_id>")
                    print("  ref_type: location, transaction, message, journal_entry, etc.")
                    return True
                contact_id = args[2]
                ref_type = args[3]
                ref_id = args[4]
                try:
                    contact_reg.add_cross_ref(contact_id, ref_type, ref_id)
                    print(f"Cross-reference added: {contact_id} -> {ref_type}:{ref_id}")
                    return True
                except Exception as e:
                    print(f"Error adding cross-reference: {e}")
                    return True
            elif ref_action == 'list':
                if len(args) < 3:
                    print("Usage: contact ref list <contact_id> [ref_type]")
                    return True
                contact_id = args[2]
                ref_type = args[3] if len(args) > 3 else None
                contact = contact_reg.get_contact(contact_id)
                if contact is None:
                    print(f"Contact not found: {contact_id}")
                    return True
                refs = contact_reg.get_cross_refs(contact_id, ref_type)
                print("\n" + "─" * 60)
                print(f"  CROSS-REFERENCES: {contact.get('display_name', contact_id)}")
                print("─" * 60)
                if ref_type:
                    print(f"  {ref_type}: {refs}")
                else:
                    for rt, rids in refs.items():
                        print(f"  {rt}: {rids}")
                print("─" * 60 + "\n")
                return True
            else:
                print(f"Unknown ref action: {ref_action}")
                print("Usage: contact ref <add|list>")
                return True

        if subcommand == 'merge':
            if len(args) < 3:
                print("Usage: contact merge <source_id> <target_id>")
                return True
            source_id = args[1]
            target_id = args[2]
            source = contact_reg.get_contact(source_id)
            target = contact_reg.get_contact(target_id)
            if source is None:
                print(f"Source contact not found: {source_id}")
                return True
            if target is None:
                print(f"Target contact not found: {target_id}")
                return True

            try:
                merged = contact_reg.merge_contact(source_id, target_id)
                print(f"Contacts merged into '{merged['display_name']}'.")
                return True
            except Exception as e:
                print(f"Error merging contacts: {e}")
                logger.error(f"Error merging contacts: {e}")
                return True

        if subcommand == 'export':
            if len(args) < 2:
                print("Usage: contact export <contact_id>")
                return True
            contact_id = args[1]
            try:
                exported = contact_reg.export_contact(contact_id)
                print(json.dumps(exported, indent=2))
                return True
            except Exception as e:
                print(f"Error exporting contact: {e}")
                return True

        if subcommand == 'import':
            if len(args) < 2:
                print("Usage: contact import <json_string>")
                return True
            json_string = ' '.join(args[1:])
            try:
                contact = contact_reg.import_contact(json_string)
                print(f"Contact '{contact['display_name']}' imported.")
                print(f"  ID: {contact['id']}")
                return True
            except Exception as e:
                print(f"Error importing contact: {e}")
                logger.error(f"Error importing contact: {e}")
                return True

        if subcommand == 'stats':
            stats = contact_reg.get_stats()
            print("\n" + "─" * 60)
            print("  CONTACT STATISTICS")
            print("─" * 60)
            print(f"  Total contacts:     {stats['total_contacts']}")
            for level, count in stats['by_trust_level'].items():
                print(f"    {level:12} {count}")
            print(f"  Total devices:      {stats['total_devices']}")
            print(f"  Contacts with refs: {stats['contacts_with_refs']}")
            print("─" * 60 + "\n")
            return True

        print(f"Unknown subcommand: {subcommand}")
        print("Usage: contact <list|add|show|update|remove|search|ref|merge|export|import|stats>")
        return True

    def cmd_link(self, args) -> bool:
        """Show link status and verify encryption."""
        subcommand = args[0] if args else 'list'

        if subcommand == 'verify':
            return self._cmd_link_verify(args[1:] if len(args) > 1 else [])

        print("\n" + "─" * 50)
        print("  LINK STATUS")
        print("─" * 50)

        sync = getattr(self.app, 'sync_engine', None)
        if not sync:
            print("  Sync engine not available.")
            print("─" * 50 + "\n")
            return True

        links = getattr(sync, '_links', {})
        if not links:
            print("  No active links.")
            print("  Use 'link verify <peer>' to create and verify a link.")
            print("─" * 50 + "\n")
            return True

        import RNS
        status_names = {
            RNS.Link.PENDING: "PENDING",
            RNS.Link.HANDSHAKE: "HANDSHAKE",
            RNS.Link.ACTIVE: "ACTIVE",
            RNS.Link.CLOSED: "CLOSED",
            RNS.Link.STALE: "STALE",
        }

        for peer_id, link in links.items():
            peer_name = getattr(link.destination, 'name', peer_id.hex()[:16]) if link.destination else peer_id.hex()[:16]
            status = status_names.get(link.status, str(link.status))
            initiator = "Initiator" if link.initiator else "Responder"

            print(f"  Peer: {peer_name}")
            print(f"    Status: {status}")
            print(f"    Role: {initiator}")

            if link.status == RNS.Link.ACTIVE and link.rtt:
                print(f"    RTT: {link.rtt:.4f}s")

            try:
                enc_status = link.get_encryption_status()
                if enc_status:
                    print(f"    Encryption: {enc_status}")
                else:
                    print(f"    Encryption: Not available")
            except Exception:
                print(f"    Encryption: Not available")

            print()

        print("─" * 50 + "\n")
        return True

    def _cmd_link_verify(self, args) -> bool:
        """Verify a link by creating a test connection."""
        import RNS

        if not args:
            print("Usage: link verify <peer_id_or_name>")
            print("\nAvailable peers (from reticulum service):")
            ret_service = getattr(self.app, 'reticulum_service', None)
            if ret_service:
                for peer in ret_service.get_peers():
                    print(f"  {peer.name} ({peer.id.hex()[:16]}...)")
            return True

        target = args[0]
        sync = getattr(self.app, 'sync_engine', None)
        ret_service = getattr(self.app, 'reticulum_service', None)

        if not sync or not ret_service:
            print("  Error: sync_engine or reticulum_service not available")
            print("─" * 50 + "\n")
            return True

        peer_id = None
        if len(target) == 32 and all(c in '0123456789abcdefABCDEF' for c in target):
            try:
                peer_id = bytes.fromhex(target)
            except ValueError:
                pass

        if not peer_id:
            for peer in ret_service.get_peers():
                if peer.name == target or target in peer.name:
                    peer_id = peer.id
                    break

        if not peer_id:
            print(f"  Error: peer '{target}' not found")
            print("  Use 'peers' command to see available peers")
            print("─" * 50 + "\n")
            return True

        async def verify_link():
            link = ret_service.create_link(peer_id.hex())
            if not link:
                return False, "Failed to create link"

            for _ in range(20):
                await asyncio.sleep(0.5)
                if link.status == RNS.Link.ACTIVE:
                    rtt = link.rtt if link.rtt else 0
                    return True, f"Link ACTIVE (RTT: {rtt:.3f}s)"
                elif link.status == RNS.Link.CLOSED:
                    return False, "Link closed during verification"

            try:
                link.teardown()
            except Exception:
                pass
            return False, "Link verification timed out (10s)"

        success, message = asyncio.run(verify_link())

        print(f"\n  Verifying link to {target}...")
        if success:
            print(f"  ✓ SUCCESS: {message}")
        else:
            print(f"  ✗ FAILED: {message}")
        print("─" * 50 + "\n")
        return True

    def cmd_logs(self, args) -> bool:
        """Show application logs."""
        import argparse
        import os
        import time

        parser = argparse.ArgumentParser(prog='logs', add_help=False)
        parser.add_argument('lines', nargs='?', type=int, default=50)
        parser.add_argument('-f', '--follow', action='store_true')
        parser.add_argument('--level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default=None)

        try:
            parsed = parser.parse_args(args)
        except SystemExit:
            return True

        log_path = os.path.expanduser('~/.local/share/pcos/logs/app.log')

        if not os.path.exists(log_path):
            print(f"Log file not found: {log_path}")
            return True

        level_priority = {
            'DEBUG': 0,
            'INFO': 1,
            'WARNING': 2,
            'ERROR': 3,
        }

        min_level = level_priority[parsed.level] if parsed.level else -1

        def read_lines(num_lines):
            try:
                with open(log_path, 'r') as f:
                    all_lines = f.readlines()
                filtered = []
                for line in all_lines[-num_lines:]:
                    if parsed.level:
                        for lvl in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
                            if lvl in line:
                                if level_priority[lvl] >= min_level:
                                    filtered.append(line)
                                break
                    else:
                        filtered.append(line)
                return filtered
            except Exception as e:
                print(f"Error reading log file: {e}")
                return []

        def tail_logs():
            try:
                with open(log_path, 'r') as f:
                    f.seek(0, 2)
                    while True:
                        line = f.readline()
                        if not line:
                            time.sleep(0.5)
                            continue
                        if parsed.level:
                            for lvl in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
                                if lvl in line:
                                    if level_priority[lvl] >= min_level:
                                        print(line.rstrip())
                                    break
                        else:
                            print(line.rstrip())
            except KeyboardInterrupt:
                return
            except Exception as e:
                print(f"Error tailing log: {e}")

        if parsed.follow:
            print(f"Tailing {log_path} (Ctrl+C to exit)...\n")
            tail_logs()
        else:
            lines = read_lines(parsed.lines)
            if lines:
                for line in lines:
                    print(line.rstrip())
            else:
                print("No matching log entries found.")
        return True

    def cmd_remote(self, args) -> bool:
        """Execute a command on a remote peer."""
        import argparse
        
        parser = argparse.ArgumentParser(prog='remote', add_help=False)
        parser.add_argument('peer', nargs='?', default=None)
        parser.add_argument('command', nargs=argparse.REMAINDER, default=None)
        parser.add_argument('-t', '--timeout', type=float, default=30.0)
        
        try:
            parsed = parser.parse_args(args)
        except SystemExit:
            return True
        
        parsed.command = ' '.join(parsed.command) if isinstance(parsed.command, list) else parsed.command
        
        if not parsed.peer or not parsed.command:
            print("\n" + "─" * 50)
            print("  REMOTE COMMAND EXECUTION")
            print("─" * 50)
            print("  Usage: remote <peer> <command> [-t timeout]")
            print("")
            print("  Example: remote debian 'echo hello'")
            print("           remote debian 'ps aux'")
            print("           remote debian 'ls -la ~/Sync'")
            print("           remote debian 'cat /proc/uptime'")
            print("           remote debian 'restart sync' -t 60")
            print("")
            print("  Available peers:")
            ret_service = getattr(self.app, 'reticulum_service', None)
            if ret_service:
                for peer in ret_service.get_peers():
                    print(f"    • {peer.name} ({peer.id[:16]}...)")
            else:
                print("    (no peers available)")
            print("─" * 50 + "\n")
            return True
        
        # Find peer by name or ID
        ret_service = getattr(self.app, 'reticulum_service', None)
        if not ret_service:
            print("Error: reticulum service not available")
            return True
        
        target_peer = None
        for peer in ret_service.get_peers():
            if peer.name == parsed.peer or parsed.peer in peer.id:
                target_peer = peer
                break
        
        if not target_peer:
            print(f"Error: peer '{parsed.peer}' not found")
            return True
        
        print(f"\nExecuting on {target_peer.name}...")
        
        async def run_command():
            return await ret_service.execute_command(
                target_peer.id,
                parsed.command,
                timeout=parsed.timeout
            )
        
        try:
            result = asyncio.run(run_command())
            if result:
                print("\n" + "─" * 50)
                print(f"  RESULT (exit code: {result.get('exit_code', '?')})")
                print("─" * 50)
                if result.get('stdout'):
                    print(result['stdout'])
                if result.get('stderr'):
                    print(f"[stderr]: {result['stderr']}")
                if result.get('error'):
                    print(f"[error]: {result['error']}")
                print("─" * 50 + "\n")
            else:
                print("Error: command execution failed (no response)")
        except Exception as e:
            print(f"Error: {e}")
        
        return True
