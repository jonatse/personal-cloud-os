"""System Tray for Personal Cloud OS."""
import os
import sys
import threading
import subprocess
from typing import Optional


class SystemTray:
    """
    System tray icon for Personal Cloud OS.
    
    Shows running status and provides menu to open CLI.
    """
    
    def __init__(self, app):
        """Initialize system tray."""
        self.app = app
        self.running = False
        self.tray = None
    
    def start(self):
        """Start the system tray."""
        if self.running:
            return
        
        self.running = True
        
        # Try to use pystray
        try:
            import pystray
            from PIL import Image, ImageDraw
            
            # Create a simple icon
            width = 64
            height = 64
            image = Image.new('RGB', (width, height), 'black')
            dc = ImageDraw.Draw(image)
            
            # Draw a cloud shape
            dc.ellipse([10, 20, 30, 40], fill='white')
            dc.ellipse([20, 15, 45, 40], fill='white')
            dc.ellipse([35, 20, 50, 35], fill='white')
            dc.rectangle([20, 35, 45, 50], fill='white')
            
            # Create menu
            menu = pystray.Menu(
                pystray.MenuItem('Open CLI', self._open_cli),
                pystray.MenuItem('Status', self._show_status),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('Quit', self._quit),
            )
            
            self.tray = pystray.Icon(
                "pcos",
                image,
                "Personal Cloud OS",
                menu
            )
            
            # Run in separate thread
            self.tray_thread = threading.Thread(target=self.tray.run, daemon=True)
            self.tray_thread.start()
            
        except ImportError:
            print("pystray not installed. Running without system tray.")
            print("Install with: pip install pystray Pillow")
            self.running = False
    
    def _open_cli(self):
        """Open CLI interface."""
        # Open CLI in new terminal
        python = sys.executable
        script = os.path.join(os.path.dirname(__file__), '..', 'main.py')
        
        terminals = [
            ['gnome-terminal', '--', python, script, '--cli'],
            ['konsole', '-e', python, script, '--cli'],
            ['xterm', '-e', python, script, '--cli'],
            ['mate-terminal', '--', python, script, '--cli'],
        ]
        
        for term in terminals:
            try:
                subprocess.Popen(term, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except FileNotFoundError:
                continue
        
        print("Could not open terminal. Run: python main.py --cli")
    
    def _show_status(self):
        """Show status."""
        print("\nPersonal Cloud OS Status:")
        print("  Running: Yes")
        print("  Use 'python main.py --cli' for full interface")
    
    def _quit(self):
        """Quit the application."""
        self.stop()
        # Stop the main app
        if hasattr(self.app, 'stop'):
            import asyncio
            loop = asyncio.new_event_loop()
            loop.run_until_complete(self.app.stop())
        sys.exit(0)
    
    def stop(self):
        """Stop the system tray."""
        self.running = False
        if self.tray:
            self.tray.stop()


def create_tray_icon():
    """Create a simple tray icon image."""
    from PIL import Image, ImageDraw
    
    width = 64
    height = 64
    image = Image.new('RGB', (width, height), '#2e3440')
    dc = ImageDraw.Draw(image)
    
    # Draw cloud
    dc.ellipse([12, 22, 28, 38], fill='#88c0d0')
    dc.ellipse([22, 16, 44, 38], fill='#88c0d0')
    dc.ellipse([36, 22, 50, 36], fill='#88c0d0')
    dc.rectangle([22, 34, 44, 46], fill='#88c0d0')
    
    return image
