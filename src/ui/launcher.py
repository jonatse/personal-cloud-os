"""App Launcher / Display - UI for interacting with the system."""
import asyncio
import logging
import time
from typing import Dict, Callable, Optional
from dataclasses import dataclass
from datetime import datetime

try:
    import tkinter as tk
    from tkinter import ttk, scrolledtext
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False
    tk = None
    ttk = None
    scrolledtext = None


logger = logging.getLogger(__name__)


@dataclass
class AppInfo:
    """Information about an app."""
    id: str
    name: str
    icon: str = ""
    description: str = ""
    command: str = ""


class AppLauncher:
    """
    App Launcher / Display UI.
    
    Provides interface for opening apps (terminal, calendar, files),
    displaying container output, and showing system status.
    Only needed when user is actively using the system.
    """
    
    # Built-in apps
    BUILT_IN_APPS = [
        AppInfo(
            id="terminal",
            name="Terminal",
            description="Access your Linux shell",
            command="terminal"
        ),
        AppInfo(
            id="files",
            name="Files",
            description="Browse and manage files",
            command="files"
        ),
        AppInfo(
            id="calendar",
            name="Calendar",
            description="View calendar and events",
            command="calendar"
        ),
        AppInfo(
            id="editor",
            name="Text Editor",
            description="Edit text files",
            command="editor"
        ),
        AppInfo(
            id="settings",
            name="Settings",
            description="Configure system",
            command="settings"
        ),
    ]
    
    def __init__(self, config, event_bus, discovery_service, sync_engine, container_manager):
        """Initialize app launcher."""
        self.config = config
        self.event_bus = event_bus
        self.discovery_service = discovery_service
        self.sync_engine = sync_engine
        self.container_manager = container_manager
        
        self._root: Optional[tk.Tk] = None
        self._running = False
        self._open_apps: Dict[str, tk.Toplevel] = {}
        
        # Register event handlers
        self._register_events()
    
    def _register_events(self):
        """Register event handlers."""
        self.event_bus.subscribe("peer.discovered", self._on_peer_discovered)
        self.event_bus.subscribe("peer.lost", self._on_peer_lost)
        self.event_bus.subscribe("sync.completed", self._on_sync_completed)
        self.event_bus.subscribe("sync.started", self._on_sync_started)
        self.event_bus.subscribe("container.started", self._on_container_started)
        self.event_bus.subscribe("container.stopped", self._on_container_stopped)
        self.event_bus.subscribe("reticulum.started", self._on_reticulum_started)
    
    def _on_peer_discovered(self, event):
        """Handle peer discovered event."""
        if self._root and self._root.winfo_exists():
            self._root.after(0, lambda: self._update_status())
    
    def _on_peer_lost(self, event):
        """Handle peer lost event."""
        if self._root and self._root.winfo_exists():
            self._root.after(0, lambda: self._update_status())
    
    def _on_sync_completed(self, event):
        """Handle sync completed event."""
        if self._root and self._root.winfo_exists():
            self._root.after(0, lambda: self._update_status())
    
    def _on_sync_started(self, event):
        """Handle sync started event."""
        if self._root and self._root.winfo_exists():
            self._root.after(0, lambda: self._update_status())
    
    def _on_container_started(self, event):
        """Handle container started event."""
        if self._root and self._root.winfo_exists():
            self._root.after(0, lambda: self._update_status())
    
    def _on_container_stopped(self, event):
        """Handle container stopped event."""
        if self._root and self._root.winfo_exists():
            self._root.after(0, lambda: self._update_status())
    
    def _on_reticulum_started(self, event):
        """Handle Reticulum started event."""
        if self._root and self._root.winfo_exists():
            self._root.after(0, lambda: self._update_status())
    
    def start(self):
        """Start the app launcher UI."""
        if self._running:
            logger.warning("App launcher already running")
            return
        
        logger.info("Starting app launcher...")
        self._running = True
        
        if not TKINTER_AVAILABLE:
            logger.info("App launcher running in headless mode (no GUI)")
            self._run_headless_loop()
            return
        
        # Create main window
        self._root = tk.Tk()
        self._root.title("Personal Cloud OS")
        self._root.geometry("800x600")
        self._root.configure(bg="#1e1e2e")
        
        # Build UI
        self._build_ui()
        
        # Start update loop
        self._update_loop()
        
        # Handle window close
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Run main loop
        self._root.mainloop()
    
    def _run_headless_loop(self):
        """Run the launcher in headless mode with periodic status logging."""
        logger.info("Starting headless status loop...")
        while self._running:
            # Log peer status
            peer_count = self.discovery_service.peer_count
            peers = self.discovery_service.get_peers()
            if peer_count > 0:
                peer_names = ", ".join([p.name for p in peers[:3]])
                if len(peers) > 3:
                    peer_names += f" (+{len(peers)-3} more)"
                logger.info(f"Headless status - Peers: {peer_count} ({peer_names})")
            else:
                logger.info("Headless status - Peers: Searching on network...")
            
            # Log sync status
            sync_status_data = self.sync_engine.get_status()
            sync_text = f"Sync: {sync_status_data.state}"
            if sync_status_data.files_synced > 0:
                sync_text += f" ({sync_status_data.files_synced}/{sync_status_data.files_total})"
            logger.info(f"Headless status - {sync_text}")
            
            # Sleep between status updates
            for _ in range(10):
                if not self._running:
                    break
                time.sleep(1)
        
        logger.info("Headless status loop stopped")
    
    def _build_ui(self):
        """Build the main UI."""
        # Header
        header = tk.Frame(self._root, bg="#1e1e2e", height=60)
        header.pack(fill=tk.X, padx=20, pady=10)
        
        # Title
        title_label = tk.Label(
            header,
            text="Personal Cloud OS",
            font=("Helvetica", 20, "bold"),
            fg="#cdd6f4",
            bg="#1e1e2e"
        )
        title_label.pack(side=tk.LEFT)
        
        # Status bar
        self._status_frame = tk.Frame(header, bg="#1e1e2e")
        self._status_frame.pack(side=tk.RIGHT)
        
        # Status indicators will be added by _update_status
        
        # Main content area
        main = tk.Frame(self._root, bg="#1e1e2e")
        main.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Network status section
        network_frame = tk.Frame(main, bg="#1e1e2e")
        network_frame.pack(fill=tk.X, pady=(0, 10))
        
        network_label = tk.Label(
            network_frame,
            text="Network Status",
            font=("Helvetica", 14, "bold"),
            fg="#cdd6f4",
            bg="#1e1e2e"
        )
        network_label.pack(anchor=tk.W)
        
        # Network info
        self._network_info = tk.Label(
            network_frame,
            text="Initializing Reticulum...",
            font=("Helvetica", 10),
            fg="#f9e2af",
            bg="#1e1e2e",
            anchor=tk.W
        )
        self._network_info.pack(fill=tk.X, pady=5)
        
        # Peers list
        self._peers_label = tk.Label(
            network_frame,
            text="Peers: Searching...",
            font=("Helvetica", 10),
            fg="#cdd6f4",
            bg="#1e1e2e",
            anchor=tk.W
        )
        self._peers_label.pack(fill=tk.X)
        
        # Apps section
        apps_label = tk.Label(
            main,
            text="Apps",
            font=("Helvetica", 14, "bold"),
            fg="#cdd6f4",
            bg="#1e1e2e"
        )
        apps_label.pack(anchor=tk.W, pady=(10, 10))
        
        # App buttons grid
        apps_frame = tk.Frame(main, bg="#1e1e2e")
        apps_frame.pack(fill=tk.X)
        
        for i, app in enumerate(self.BUILT_IN_APPS):
            btn = tk.Button(
                apps_frame,
                text=app.name,
                font=("Helvetica", 12),
                bg="#45475a",
                fg="#cdd6f4",
                activebackground="#585b70",
                activeforeground="#cdd6f4",
                relief=tk.FLAT,
                padx=20,
                pady=15,
                command=lambda a=app: self._launch_app(a)
            )
            btn.grid(row=i // 3, column=i % 3, padx=5, pady=5, sticky="nsew")
        
        # Configure grid
        for i in range(3):
            apps_frame.columnconfigure(i, weight=1)
        
        # Log/output section
        log_label = tk.Label(
            main,
            text="System Log",
            font=("Helvetica", 14, "bold"),
            fg="#cdd6f4",
            bg="#1e1e2e"
        )
        log_label.pack(anchor=tk.W, pady=(20, 10))
        
        # Log text area
        self._log_text = scrolledtext.ScrolledText(
            main,
            font=("Courier", 10),
            bg="#11111b",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            height=10
        )
        self._log_text.pack(fill=tk.BOTH, expand=True)
        
        # Initial status update
        self._update_status()
    
    def _update_status(self):
        """Update status indicators."""
        # Clear existing status (legacy - now using network section)
        for widget in self._status_frame.winfo_children():
            widget.destroy()
        
        # Update network status
        if hasattr(self, '_network_info'):
            # Check if Reticulum is running (via discovery service)
            reticulum_running = self.discovery_service.is_running()
            
            if reticulum_running:
                # Try to get identity hash
                try:
                    identity = getattr(self.discovery_service, '_reticulum_service', None)
                    if identity:
                        identity_hash = identity.get_identity_hash()
                        if identity_hash:
                            self._network_info.config(
                                text=f"Reticulum: Online (Identity: {identity_hash[:16]}...)",
                                fg="#a6e3a1"
                            )
                        else:
                            self._network_info.config(
                                text="Reticulum: Online",
                                fg="#a6e3a1"
                            )
                    else:
                        self._network_info.config(
                            text="Reticulum: Initializing...",
                            fg="#f9e2af"
                        )
                except Exception:
                    self._network_info.config(
                        text="Reticulum: Online",
                        fg="#a6e3a1"
                    )
            else:
                self._network_info.config(
                    text="Reticulum: Starting...",
                    fg="#f9e2af"
                )
        
        # Update peers label
        if hasattr(self, '_peers_label'):
            peer_count = self.discovery_service.peer_count
            peers = self.discovery_service.get_peers()
            
            if peer_count > 0:
                peer_names = ", ".join([p.name for p in peers[:3]])
                if len(peers) > 3:
                    peer_names += f" (+{len(peers)-3} more)"
                self._peers_label.config(
                    text=f"Peers: {peer_count} ({peer_names})",
                    fg="#a6e3a1"
                )
            else:
                self._peers_label.config(
                    text="Peers: Searching on network...",
                    fg="#f9e2af"
                )
        
        # Legacy status bar - Container
        container_running = self.container_manager.is_running()
        container_color = "#a6e3a1" if container_running else "#f38ba8"
        container_status = tk.Label(
            self._status_frame,
            text=f"Container: {'Running' if container_running else 'Stopped'}",
            font=("Helvetica", 10),
            fg=container_color,
            bg="#1e1e2e"
        )
        container_status.pack(side=tk.LEFT, padx=10)
        
        # Legacy status bar - Sync
        sync_status_data = self.sync_engine.get_status()
        sync_color = "#a6e3a1" if sync_status_data.state == "idle" else "#f9e2af"
        sync_text = f"Sync: {sync_status_data.state}"
        if sync_status_data.files_synced > 0:
            sync_text += f" ({sync_status_data.files_synced}/{sync_status_data.files_total})"
        sync_status = tk.Label(
            self._status_frame,
            text=sync_text,
            font=("Helvetica", 10),
            fg=sync_color,
            bg="#1e1e2e"
        )
        sync_status.pack(side=tk.LEFT, padx=10)
    
    def _update_loop(self):
        """Periodic UI update loop."""
        if not self._running or not self._root:
            return
        
        self._update_status()
        
        # Schedule next update
        if self._root and self._root.winfo_exists():
            self._root.after(2000, self._update_loop)
    
    def _launch_app(self, app: AppInfo):
        """Launch an app."""
        logger.info(f"Launching app: {app.name}")
        
        # Publish event
        asyncio.create_task(self.event_bus.publish(type="app.launched", data={"app_id": app.id, "app_name": app.name}, source="ui"))
        
        # Open app window
        if app.id == "terminal":
            self._open_terminal()
        elif app.id == "files":
            self._open_files()
        elif app.id == "calendar":
            self._open_calendar()
        elif app.id == "editor":
            self._open_editor()
        elif app.id == "settings":
            self._open_settings()
    
    def _open_terminal(self):
        """Open terminal window."""
        if "terminal" in self._open_apps:
            self._open_apps["terminal"].focus()
            return
        
        window = tk.Toplevel(self._root)
        window.title("Terminal")
        window.geometry("600x400")
        window.configure(bg="#11111b")
        
        # Terminal output area
        term = tk.Text(
            window,
            font=("Courier", 12),
            bg="#11111b",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            wrap=tk.WORD
        )
        term.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Input area
        input_frame = tk.Frame(window, bg="#11111b")
        input_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        input_label = tk.Label(
            input_frame,
            text="$ ",
            font=("Courier", 12),
            fg="#a6e3a1",
            bg="#11111b"
        )
        input_label.pack(side=tk.LEFT)
        
        entry = tk.Entry(
            input_frame,
            font=("Courier", 12),
            bg="#45475a",
            fg="#cdd6f4",
            insertbackground="#cdd6f4",
            relief=tk.FLAT
        )
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        def run_command(event=None):
            cmd = entry.get()
            if cmd:
                term.insert(tk.END, f"$ {cmd}\n")
                term.insert(tk.END, f"[Command would execute in container: {cmd}]\n\n")
                term.see(tk.END)
                entry.delete(0, tk.END)
        
        entry.bind("<Return>", run_command)
        entry.focus()
        
        self._open_apps["terminal"] = window
        
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_app("terminal", window))
    
    def _open_files(self):
        """Open files window."""
        if "files" in self._open_apps:
            self._open_apps["files"].focus()
            return
        
        window = tk.Toplevel(self._root)
        window.title("Files")
        window.geometry("600x400")
        window.configure(bg="#1e1e2e")
        
        label = tk.Label(
            window,
            text="File Browser",
            font=("Helvetica", 14),
            fg="#cdd6f4",
            bg="#1e1e2e"
        )
        label.pack(pady=20)
        
        sync_dir = self.sync_engine.sync_dir
        dir_label = tk.Label(
            window,
            text=f"Sync Directory: {sync_dir}",
            font=("Helvetica", 10),
            fg="#a6e3a1",
            bg="#1e1e2e"
        )
        dir_label.pack()
        
        self._open_apps["files"] = window
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_app("files", window))
    
    def _open_calendar(self):
        """Open calendar window."""
        if "calendar" in self._open_apps:
            self._open_apps["calendar"].focus()
            return
        
        window = tk.Toplevel(self._root)
        window.title("Calendar")
        window.geometry("400x300")
        window.configure(bg="#1e1e2e")
        
        label = tk.Label(
            window,
            text="Calendar",
            font=("Helvetica", 18),
            fg="#cdd6f4",
            bg="#1e1e2e"
        )
        label.pack(pady=20)
        
        date_label = tk.Label(
            window,
            text=datetime.now().strftime("%B %d, %Y"),
            font=("Helvetica", 24),
            fg="#f9e2af",
            bg="#1e1e2e"
        )
        date_label.pack()
        
        self._open_apps["calendar"] = window
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_app("calendar", window))
    
    def _open_editor(self):
        """Open text editor window."""
        if "editor" in self._open_apps:
            self._open_apps["editor"].focus()
            return
        
        window = tk.Toplevel(self._root)
        window.title("Text Editor")
        window.geometry("600x400")
        window.configure(bg="#1e1e2e")
        
        text = tk.Text(
            window,
            font=("Courier", 12),
            bg="#11111b",
            fg="#cdd6f4",
            insertbackground="#cdd6f4"
        )
        text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self._open_apps["editor"] = window
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_app("editor", window))
    
    def _open_settings(self):
        """Open settings window."""
        if "settings" in self._open_apps:
            self._open_apps["settings"].focus()
            return
        
        window = tk.Toplevel(self._root)
        window.title("Settings")
        window.geometry("500x400")
        window.configure(bg="#1e1e2e")
        
        label = tk.Label(
            window,
            text="Settings",
            font=("Helvetica", 18),
            fg="#cdd6f4",
            bg="#1e1e2e"
        )
        label.pack(pady=20)
        
        # Settings sections
        settings_frame = tk.Frame(window, bg="#1e1e2e")
        settings_frame.pack(fill=tk.BOTH, expand=True, padx=20)
        
        # Network section
        network_frame = tk.LabelFrame(
            settings_frame,
            text="Reticulum Network",
            font=("Helvetica", 12, "bold"),
            fg="#cdd6f4",
            bg="#1e1e2e"
        )
        network_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(
            network_frame,
            text="ZeroTrust encrypted networking enabled",
            fg="#a6e3a1",
            bg="#1e1e2e"
        ).pack(anchor=tk.W, padx=10, pady=5)
        
        tk.Label(
            network_frame,
            text="Note: Same identity = automatic peer discovery",
            fg="#cdd6f4",
            bg="#1e1e2e"
        ).pack(anchor=tk.W, padx=10, pady=2)
        
        # Sync section
        sync_frame = tk.LabelFrame(
            settings_frame,
            text="Sync",
            font=("Helvetica", 12, "bold"),
            fg="#cdd6f4",
            bg="#1e1e2e"
        )
        sync_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(
            sync_frame,
            text=f"Sync Interval: {self.config.get('sync.sync_interval')}s",
            fg="#cdd6f4",
            bg="#1e1e2e"
        ).pack(anchor=tk.W, padx=10, pady=5)
        
        self._open_apps["settings"] = window
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_app("settings", window))
    
    def _close_app(self, app_id: str, window: tk.Toplevel):
        """Close an app window."""
        if app_id in self._open_apps:
            del self._open_apps[app_id]
        
        window.destroy()
        
        asyncio.create_task(self.event_bus.publish(type="app.closed", data={"app_id": app_id}, source="ui"))
    
    def _on_close(self):
        """Handle main window close."""
        # Hide window instead of closing (background services keep running)
        self._root.withdraw()
    
    def show(self):
        """Show the main window."""
        if self._root:
            self._root.deiconify()
            self._root.focus()
    
    def is_running(self):
        """Check if the launcher is still running."""
        return self._running

    def stop(self):
        """Stop the UI."""
        self._running = False
        if self._root:
            self._root.quit()
            self._root = None
    
    def log_message(self, message: str):
        """Add a message to the log."""
        if self._root and self._root.winfo_exists():
            self._root.after(0, lambda: self._log_text.insert(tk.END, f"{message}\n"))
            self._root.after(0, lambda: self._log_text.see(tk.END))
