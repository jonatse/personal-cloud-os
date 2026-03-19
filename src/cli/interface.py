"""Interactive CLI Interface for Personal Cloud OS."""
import sys
import os
from .commands import CommandHandler


class CLIInterface:
    """
    Interactive CLI shell for managing Personal Cloud OS.
    """
    
    def __init__(self, app):
        """Initialize CLI with app reference."""
        self.app = app
        self.command_handler = CommandHandler(app)
        self.running = False
    
    def start(self):
        """Start the CLI interface."""
        self.running = True
        
        # Print welcome
        self._print_welcome()
        
        # Show initial status
        self.command_handler.execute('status')
        
        # Main command loop
        while self.running:
            try:
                prompt = "\033[1;36mpcos\033[0m \033[1;34m❯\033[0m "
                cmd = input(prompt).strip()
                
                if cmd:
                    result = self.command_handler.execute(cmd)
                    if not result:
                        break
                    # Print enhanced status after each command
                    print()
                    self._print_status_bar()
                    
            except KeyboardInterrupt:
                print("\nUse 'exit' to close CLI, 'quit' to stop the app.")
                continue
            except EOFError:
                break
        
        print("CLI session ended.")
    
    def _print_welcome(self):
        """Print welcome message."""
        print("\n" + "=" * 50)
        print("  \033[1;37mPersonal Cloud OS\033[0m v1.0")
        print("=" * 50)
        print("  \033[1;32m✓\033[0m Running in background")
        print("  \033[1;32m✓\033[0m Network: Online")
        print("  \033[1;32m✓\033[0m Tray icon: Active")
        print("-" * 50)
        print("  Type '\033[1;33mhelp\033[0m' for available commands")
        print("  Type '\033[1;33mexit\033[0m' to close CLI (keeps running)")
        print("  Type '\033[1;33mquit\033[0m' to stop the application")
        print("=" * 50 + "\n")
    
    def _print_status_bar(self):
        """Print enhanced status bar with device, peers, and network info."""
        import socket
        import subprocess
        
        # Get services
        discovery = getattr(self.app, 'discovery_service', None)
        ret_service = getattr(self.app, 'reticulum_service', None)
        device_mgr = getattr(self.app, 'device_manager', None)
        
        # ========== DEVICE INFO ==========
        hostname = socket.gethostname()
        
        device_id = "Unknown"
        mac = "Unknown"
        if device_mgr:
            device_id = getattr(device_mgr, 'device_id', 'Unknown')
            mac = getattr(device_mgr, 'mac', 'Unknown')
        
        # ========== RETICULUM INFO ==========
        ret_identity = "Unknown"
        ret_dest = "Unknown"
        if ret_service:
            if hasattr(ret_service, '_identity_hash'):
                ret_identity = ret_service._identity_hash[:16] + "..."
            if hasattr(ret_service, '_destination_hash'):
                ret_dest = ret_service._destination_hash[:16] + "..."
        
        # ========== PEERS ==========
        peers = []
        peer_count = 0
        peer_count_raw = 0
        if discovery and hasattr(discovery, 'get_peers'):
            try:
                peers = discovery.get_peers()
                peer_count_raw = len(peers)
                peer_count = peer_count_raw
            except Exception as e:
                peer_count = f"Error: {e}"
        
        # ========== NETWORKS - USED BY RETICULUM ==========
        # Query rnsd for active interfaces
        used_networks = []
        try:
            result = subprocess.run(
                ["python3", "-c", """
import RNS, time
r = RNS.Reticulum.from_storage()
time.sleep(0.5)
for i in RNS.Transport.interfaces:
    print(f"{i.name}|{type(i).__name__}|{getattr(i, 'online', False)}")
"""],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split('|')
                    if len(parts) >= 3:
                        name, itype, online = parts
                        status = "ONLINE" if online == "True" else "offline"
                        used_networks.append(f"{name} ({itype.split('.')[-1]}) [{status}]")
        except Exception as e:
            used_networks.append(f"Query error: {e}")
        
        # ========== ALL NETWORK HARDWARE ==========
        # Get all network interfaces from system
        all_networks = []
        try:
            import psutil
            for iface, addrs in psutil.net_if_addrs().items():
                if iface != 'lo':
                    ipv4 = ""
                    for addr in addrs:
                        if addr.family == 2:  # AF_INET
                            ipv4 = addr.address
                            break
                    # Check if used by Reticulum
                    used = any(iface in net for net in used_networks)
                    status = "USED" if used else "unused"
                    all_networks.append(f"{iface}: {ipv4} [{status}]")
        except Exception as e:
            all_networks.append(f"Error: {e}")
        
        # ========== PRINT STATUS ==========
        width = 60
        print("═" * width)
        print(f"  DEVICE: {hostname}")
        print(f"    MAC: {mac}")
        print(f"    Device ID: {device_id}")
        print("═" * width)
        print(f"  RETICULUM:")
        print(f"    Identity: {ret_identity}")
        print(f"    Destination: {ret_dest}")
        print("═" * width)
        print(f"  PEERS: {peer_count} connected")
        for peer in peers[:5]:
            print(f"    • {peer.name}")
        if peer_count_raw > 5:
            print(f"    (+{peer_count_raw - 5} more)")
        if peer_count == 0:
            print(f"    (waiting for peers...)")
        print("═" * width)
        print(f"  NETWORKS USED BY RETICULUM:")
        for net in used_networks:
            print(f"    • {net}")
        if not used_networks:
            print(f"    (none detected)")
        print("═" * width)
        print(f"  ALL NETWORK HARDWARE:")
        for net in all_networks:
            print(f"    • {net}")
        print("═" * width)
        print(f"  [Enter to refresh, exit to close CLI]")
        print("═" * width)
    
    def stop(self):
        """Stop the CLI."""
        self.running = False


def open_cli(app):
    """Open the CLI interface in a new terminal."""
    import subprocess
    import sys
    
    # Get the path to this Python interpreter and script
    python = sys.executable
    script = os.path.join(os.path.dirname(__file__), '..', 'main.py')
    
    # Try to open in default terminal
    terminals = [
        ['gnome-terminal', '--', python, script, '--cli'],
        ['konsole', '-e', python, script, '--cli'],
        ['xterm', '-e', python, script, '--cli'],
        ['mate-terminal', '--', python, script, '--cli'],
        ['xfce4-terminal', '-e', python, script, '--cli'],
    ]
    
    for term in terminals:
        try:
            subprocess.Popen(term, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except FileNotFoundError:
            continue
    
    # Fallback: try to run in current terminal
    print("Could not open new terminal. Opening in current terminal...")
    cli = CLIInterface(app)
    cli.start()
    return True
