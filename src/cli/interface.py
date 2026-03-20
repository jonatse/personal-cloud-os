"""Interactive CLI Interface for Personal Cloud OS."""
import sys
import os
import logging
import threading
import time
from .commands import CommandHandler

logger = logging.getLogger(__name__)


class CLIInterface:
    """
    Interactive CLI shell for managing Personal Cloud OS.

    The status bar auto-refreshes every REFRESH_INTERVAL seconds in a
    background thread so peer discovery, sync state, etc. appear live
    without the user having to type anything.
    """

    REFRESH_INTERVAL = 5  # seconds between automatic status redraws

    def __init__(self, app):
        """Initialize CLI with app reference."""
        self.app = app
        self.command_handler = CommandHandler(app)
        self.running = False
        self._refresh_thread = None
        self._redraw_lock = threading.Lock()
        self._last_status_lines = 0   # how many lines the last status bar used

    # ------------------------------------------------------------------ #
    # Public entry point
    # ------------------------------------------------------------------ #

    def start(self):
        """Start the CLI interface."""
        self.running = True

        self._print_welcome()

        # Brief wait so Reticulum can receive first announce before we
        # print the initial status (avoids "0 peers" on first render).
        self._wait_for_peers(timeout=5)

        self._print_status_bar()

        # Start background refresh thread
        self._refresh_thread = threading.Thread(
            target=self._auto_refresh_loop,
            daemon=True,
            name="cli-refresh"
        )
        self._refresh_thread.start()

        # Main input loop
        while self.running:
            try:
                prompt = "\033[1;36mpcos\033[0m \033[1;34m❯\033[0m "
                cmd = input(prompt).strip()

                if cmd:
                    with self._redraw_lock:
                        result = self.command_handler.execute(cmd)
                    if not result:
                        break
                    with self._redraw_lock:
                        self._print_status_bar()

            except KeyboardInterrupt:
                print("\nUse 'exit' to close CLI, 'quit' to stop the app.")
                continue
            except EOFError:
                break

        self.running = False
        print("CLI session ended.")

    def stop(self):
        """Stop the CLI."""
        self.running = False

    # ------------------------------------------------------------------ #
    # Auto-refresh
    # ------------------------------------------------------------------ #

    def _auto_refresh_loop(self):
        """Background thread: redraws status bar every REFRESH_INTERVAL seconds."""
        while self.running:
            time.sleep(self.REFRESH_INTERVAL)
            if not self.running:
                break
            with self._redraw_lock:
                self._reprint_status_bar()

    def _reprint_status_bar(self):
        """Erase the previous status bar and redraw it in place."""
        # Move cursor up past the previous status block and clear it
        if self._last_status_lines > 0:
            sys.stdout.write(f"\033[{self._last_status_lines}A")  # cursor up
            sys.stdout.write("\033[J")                             # clear to end
            sys.stdout.flush()
        self._print_status_bar()

    # ------------------------------------------------------------------ #
    # Startup helper
    # ------------------------------------------------------------------ #

    def _wait_for_peers(self, timeout=5):
        """
        Block for up to `timeout` seconds waiting for the first peer announce.
        Returns immediately if a peer is already known or if timeout expires.
        """
        ret = getattr(self.app, 'reticulum_service', None)
        if not ret:
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            if ret.get_peers():
                return
            time.sleep(0.25)

    # ------------------------------------------------------------------ #
    # Rendering
    # ------------------------------------------------------------------ #

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
        """Render the live status bar and record how many lines it used."""
        import socket
        import subprocess

        ret_service = getattr(self.app, 'reticulum_service', None)
        device_mgr  = getattr(self.app, 'device_manager', None)
        sync        = getattr(self.app, 'sync_engine', None)
        container   = getattr(self.app, 'container_manager', None)

        # --- device ---
        hostname  = socket.gethostname()
        device_id = getattr(device_mgr, 'device_id', 'Unknown') if device_mgr else 'Unknown'
        mac       = getattr(device_mgr, 'mac', 'Unknown')       if device_mgr else 'Unknown'

        # --- reticulum ---
        ret_identity = "Unknown"
        ret_dest     = "Unknown"
        if ret_service:
            if hasattr(ret_service, '_identity_hash'):
                ret_identity = ret_service._identity_hash[:16] + "..."
            if hasattr(ret_service, '_destination_hash'):
                ret_dest = ret_service._destination_hash[:16] + "..."

        # --- peers ---
        peers = []
        if ret_service and hasattr(ret_service, 'get_peers'):
            try:
                seen = set()
                for p in ret_service.get_peers():
                    if p.name not in seen:
                        peers.append(p)
                        seen.add(p.name)
            except Exception as e:
                logger.debug(f"get_peers error: {e}")

        # --- sync ---
        sync_state = "n/a"
        sync_files = "0/0"
        if sync:
            try:
                s = sync.get_status()
                sync_state = s.state
                sync_files = f"{s.files_synced}/{s.files_total}"
            except Exception:
                pass

        # --- container ---
        container_state = "Running" if (container and container.is_running()) else "Stopped"

        # --- reticulum interfaces (fast subprocess query) ---
        ifaces = []
        try:
            result = subprocess.run(
                ["python3", "-c",
                 "import RNS\nRNS.Reticulum()\nimport time; time.sleep(0.3)\n"
                 "for i in RNS.Transport.interfaces:\n"
                 "    print(f'{i.name}|{type(i).__name__.split(\".\")[-1]}|{getattr(i,\"online\",False)}')"],
                capture_output=True, text=True, timeout=4
            )
            for line in result.stdout.strip().splitlines():
                parts = line.split('|')
                if len(parts) == 3:
                    n, t, o = parts
                    ifaces.append(f"{n} ({t}) [{'ONLINE' if o=='True' else 'offline'}]")
        except Exception:
            pass

        # --- build lines ---
        W = 58
        lines = []
        lines.append("═" * W)
        lines.append(f"  DEVICE : {hostname}  |  MAC: {mac}")
        lines.append(f"  ID     : {device_id}")
        lines.append("═" * W)
        lines.append(f"  RETICULUM")
        lines.append(f"    Identity   : {ret_identity}")
        lines.append(f"    Destination: {ret_dest}")
        lines.append("═" * W)

        peer_count = len(peers)
        status_icon = "\033[1;32m●\033[0m" if peer_count else "\033[1;33m○\033[0m"
        lines.append(f"  PEERS  : {status_icon} {peer_count} connected")
        for p in peers[:5]:
            lines.append(f"    • {p.name}")
        if peer_count > 5:
            lines.append(f"    (+{peer_count - 5} more)")
        if peer_count == 0:
            lines.append(f"    (waiting for peers...)")

        lines.append("═" * W)
        lines.append(f"  SYNC      : {sync_state}   FILES: {sync_files}")
        lines.append(f"  CONTAINER : {container_state}")
        if ifaces:
            lines.append("─" * W)
            for iface in ifaces:
                lines.append(f"  NET: {iface}")
        lines.append("═" * W)
        lines.append(f"  Auto-refreshes every {self.REFRESH_INTERVAL}s  |  'help' for commands")
        lines.append("═" * W)

        output = "\n".join(lines) + "\n"
        sys.stdout.write(output)
        sys.stdout.flush()

        # Record line count so _reprint_status_bar can erase it
        self._last_status_lines = len(lines) + 1  # +1 for trailing newline


def open_cli(app):
    """Open the CLI interface in a new terminal."""
    import subprocess

    python = sys.executable
    script = os.path.join(os.path.dirname(__file__), '..', 'main.py')

    terminals = [
        ['gnome-terminal', '--', python, script, '--cli'],
        ['konsole',        '-e', python, script, '--cli'],
        ['xterm',          '-e', python, script, '--cli'],
        ['mate-terminal',  '--', python, script, '--cli'],
        ['xfce4-terminal', '-e', python, script, '--cli'],
    ]

    for term in terminals:
        try:
            subprocess.Popen(term, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except FileNotFoundError:
            continue

    print("Could not open new terminal. Opening in current terminal...")
    CLIInterface(app).start()
    return True
