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
                    # Print compact status after each command
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
        """Print compact status bar."""
        # Get peer count
        discovery = getattr(self.app, 'discovery_service', None)
        ret_service = getattr(self.app, 'reticulum_service', None)
        
        peer_count = 0
        if discovery:
            peer_count = len(discovery.get_peers()) if hasattr(discovery, 'get_peers') else 0
        
        identity = "Unknown"
        if ret_service and hasattr(ret_service, '_identity_hash'):
            identity = ret_service._identity_hash[:12] + "..."
        
        print("─" * 50)
        print(f"  Reticulum: {identity} | Peers: {peer_count} | Press Enter to refresh")
        print("─" * 50)
    
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
