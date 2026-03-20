"""
System Tray for Personal Cloud OS.

Uses a pure-Python icon (tray/icon.py) — no Pillow required.
pystray is still needed for the tray itself but is optional:
if not installed the app runs normally without a tray icon.

Pillow has been removed as a dependency (was only used to draw
a simple cloud shape). See tray/icon.py for the replacement.
"""
import os
import sys
import threading
import subprocess
from typing import Optional


class SystemTray:
    """
    System tray icon for Personal Cloud OS.

    Shows running status and provides a menu to open the CLI.
    Falls back silently if pystray is not installed.
    """

    def __init__(self, app):
        self.app     = app
        self.running = False
        self.tray    = None

    def start(self):
        """Start the system tray. Silent no-op if pystray not available."""
        if self.running:
            return
        try:
            import pystray
        except ImportError:
            # pystray not installed — tray is optional, continue without it
            return

        self.running = True

        from tray.icon import make_icon
        image = make_icon(64)

        menu = pystray.Menu(
            pystray.MenuItem('Open CLI',  self._open_cli),
            pystray.MenuItem('Status',    self._show_status),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Quit',      self._quit),
        )

        self.tray = pystray.Icon("pcos", image, "Personal Cloud OS", menu)

        self.tray_thread = threading.Thread(
            target=self.tray.run, daemon=True, name="systray")
        self.tray_thread.start()

    def stop(self):
        """Stop the system tray."""
        self.running = False
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Menu actions
    # ------------------------------------------------------------------ #

    def _open_cli(self):
        """Open the CLI in a new terminal window."""
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
                subprocess.Popen(term,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
                return
            except FileNotFoundError:
                continue

    def _show_status(self):
        """Show basic status (tray context — no terminal available)."""
        ret  = getattr(self.app, 'reticulum_service', None)
        peers = len(ret.get_peers()) if ret else 0
        # pystray doesn't give us a window — log it instead
        import logging
        logging.getLogger(__name__).info(
            f"Status: running=True peers={peers}")

    def _quit(self):
        """Stop the application."""
        self.stop()
        loop = getattr(self.app, '_loop', None)
        if loop and loop.is_running():
            import asyncio
            asyncio.run_coroutine_threadsafe(self.app.stop(), loop)
        else:
            sys.exit(0)
