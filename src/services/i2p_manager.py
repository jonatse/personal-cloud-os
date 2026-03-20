"""
I2P Manager - Decentralized Internet Tunneling for Personal Cloud OS

Manages the i2pd daemon and configures Reticulum to use I2P as a transport,
enabling peer discovery and communication over the internet without any
central server, VPN provider, or static IP.

Architecture:
    i2pd (daemon) ← managed by this module
        ↓
    Reticulum I2PInterface ← configured automatically
        ↓
    ReticulumPeerService ← discovers peers anywhere on internet

How I2P works with Reticulum:
    - Each device runs an i2pd router that connects to the I2P network
    - i2pd creates an inbound tunnel (SAM bridge on 127.0.0.1:7656)
    - Reticulum connects to that SAM bridge via I2PInterface
    - Peers anywhere on the internet can discover each other through I2P
    - All traffic is onion-routed through I2P — encrypted and anonymous
    - No port-forwarding or static IP needed

Requirements:
    - i2pd installed: sudo apt install i2pd
    - OR: i2pd binary in PATH

Fallback behaviour:
    - If i2pd is not installed, logs a clear message and continues LAN-only
    - LAN discovery (AutoInterface) always works regardless of I2P status
    - App never fails to start due to missing i2pd

Usage:
    manager = I2PManager(config)
    await manager.start()          # starts i2pd if needed, patches RNS config
    manager.is_available()         # True if I2P is running and SAM is ready
    await manager.stop()           # stops i2pd if we started it
"""
import asyncio
import logging
import os
import subprocess
import time
import socket
import threading
import configparser
from pathlib import Path

logger = logging.getLogger(__name__)

# i2pd SAM bridge default address — Reticulum connects here
SAM_HOST = "127.0.0.1"
SAM_PORT = 7656

# How long to wait for i2pd SAM bridge to become available
SAM_STARTUP_TIMEOUT = 300   # seconds (5 minutes for first tunnel build)

# Reticulum config path
RNS_CONFIG_PATH = os.path.expanduser("~/.reticulum/config")

# I2P interface name in Reticulum config
RNS_I2P_SECTION = "PCOS I2P Interface"


class I2PManager:
    """
    Manages i2pd lifecycle and Reticulum I2P interface configuration.

    On start():
        1. Check if i2pd is installed
        2. Check if i2pd is already running (SAM bridge reachable)
        3. If not running, start i2pd as a subprocess
        4. Wait for SAM bridge to become available
        5. Patch ~/.reticulum/config to add I2PInterface if not present
        6. Signal Reticulum to reload (or note that restart is needed)

    On stop():
        1. If we started i2pd, stop it
        2. Leave Reticulum config as-is (I2P section stays for next run)
    """

    def __init__(self, config):
        self.config       = config
        self._process     = None   # subprocess.Popen if we started i2pd
        self._available   = False  # True once SAM bridge is confirmed up
        self._running     = False
        self._we_started  = False  # True if we spawned i2pd ourselves
        self._output_thread = None  # Thread to read i2pd output

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def start(self):
        """Start I2P support. Non-fatal if i2pd is not installed."""
        self._running = True
        logger.info("I2PManager: starting...")

        # Step 1: Is i2pd installed?
        i2pd_bin = self._find_i2pd()
        if not i2pd_bin:
            logger.warning(
                "I2P: i2pd not found. Internet peer discovery disabled.\n"
                "  To enable: sudo apt install i2pd\n"
                "  LAN discovery still works without i2pd."
            )
            return

        logger.info(f"I2P: found i2pd at {i2pd_bin}")

        # Step 2: Check i2pd version
        self._check_i2pd_version(i2pd_bin)

        # Step 3: Patch Reticulum config now (before RNS reads it)
        self._patch_rns_config()

        # Step 4: Is SAM bridge already up? (i2pd already running externally)
        if self._sam_reachable():
            logger.info("I2P: SAM bridge already available (i2pd already running)")
            self._available = True
            return

        # Step 5: Start i2pd in background — don't block startup.
        # The SAM bridge takes 2-5 minutes on first run while I2P builds
        # tunnels. We fire it off and let a background thread monitor it.
        # Reticulum will use the I2P interface automatically once it's ready.
        logger.info("I2P: starting i2pd in background (will not block startup)...")
        self._launch_i2pd_background(i2pd_bin)

    async def stop(self):
        """Stop i2pd if we started it."""
        self._running = False
        if self._process and self._we_started:
            logger.info("I2P: stopping i2pd...")
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception as e:
                logger.debug(f"I2P: stop error: {e}")
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._available = False
        logger.info("I2P: stopped")

    def is_available(self) -> bool:
        """True if I2P SAM bridge is up and ready for connections."""
        return self._available

    def status(self) -> dict:
        """Return current I2P status for display."""
        # Determine binary source for display
        bundled = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'bin', 'i2pd')
        )
        if self._process:
            binary_path = getattr(self._process, 'args', [''])[0]
        else:
            binary_path = self._find_i2pd() or ''

        if binary_path == bundled:
            binary_source = "bundled (src/bin/i2pd)"
        elif binary_path:
            binary_source = f"system ({binary_path})"
        else:
            binary_source = "not found"

        process_status = None
        if self._process:
            try:
                # Check if process is still running
                self._process.poll()
                if self._process.returncode is None:
                    process_status = "running"
                else:
                    process_status = f"exited with code {self._process.returncode}"
            except Exception as e:
                process_status = f"error: {e}"

        return {
            "available":      self._available,
            "sam_host":       SAM_HOST,
            "sam_port":       SAM_PORT,
            "we_started":     self._we_started,
            "binary_source":  binary_source,
            "binary_path":    binary_path,
            "process_status": process_status,
            "pid":            self._process.pid if self._process else None,
        }

    # ------------------------------------------------------------------ #
    # i2pd lifecycle
    # ------------------------------------------------------------------ #

    def _find_i2pd(self) -> str | None:
        """
        Find the i2pd binary, checking in this order:

        1. src/bin/i2pd  — bundled binary committed to the repo (preferred)
           This is the self-contained path: no system install needed.
        2. PATH          — system-installed i2pd (fallback)
        3. Common system locations (/usr/sbin, /usr/bin, /usr/local/bin)

        Returns the path to a usable binary, or None if not found.
        """
        import shutil

        # 1. Bundled binary — check multiple locations to handle both
        #    normal source layout (src/bin/i2pd) and PyInstaller bundle
        #    where files land in _internal/bin/i2pd
        import sys as _sys
        candidates = [
            # Normal source layout: src/services/../bin/i2pd
            os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', 'bin', 'i2pd')
            ),
            # PyInstaller onedir: _internal/bin/i2pd next to executable
            os.path.join(os.path.dirname(_sys.executable), 'bin', 'i2pd'),
            # PyInstaller _internal layout
            os.path.join(getattr(_sys, '_MEIPASS', ''), 'bin', 'i2pd'),
        ]
        for bundled in candidates:
            if bundled and os.path.isfile(bundled) and os.access(bundled, os.X_OK):
                logger.info(f"I2P: using bundled binary: {bundled}")
                return bundled

        # 2. System PATH
        found = shutil.which("i2pd")
        if found:
            logger.info(f"I2P: using system binary from PATH: {found}")
            return found

        # 3. Common system install locations
        for path in ["/usr/sbin/i2pd", "/usr/bin/i2pd", "/usr/local/bin/i2pd"]:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                logger.info(f"I2P: using system binary: {path}")
                return path

        return None

    def _check_i2pd_version(self, binary: str):
        """Check and log i2pd version"""
        try:
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                version_line = result.stdout.strip().split('\n')[0]
                logger.debug(f"I2P: i2pd version: {version_line}")
            else:
                logger.warning(f"I2P: could not get i2pd version: {result.stderr}")
        except Exception as e:
            logger.warning(f"I2P: version check failed: {e}")

    def _launch_i2pd_background(self, binary: str):
        """
        Start i2pd as a subprocess and monitor it in a background thread.
        Does NOT block — returns immediately.
        The background thread sets self._available once SAM is reachable.
        """
        try:
            self._process = subprocess.Popen(
                [binary, "--log=stdout", "--loglevel=info"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            self._we_started = True
            logger.info(f"I2P: i2pd started in background (pid {self._process.pid})")
            
            # Start output reading threads
            self._start_output_reading()
            
        except Exception as e:
            logger.error(f"I2P: could not launch i2pd: {e}")
            return

        # Monitor in background thread — mark available when SAM comes up
        t = threading.Thread(
            target=self._wait_for_sam,
            daemon=True,
            name="i2p-monitor"
        )
        t.start()

    def _start_output_reading(self):
        """Start threads to read and log i2pd output"""
        def read_stdout():
            while self._process and self._running:
                try:
                    line = self._process.stdout.readline()
                    if not line:
                        break
                    logger.debug(f"I2P: i2pd stdout: {line.rstrip()}")
                except Exception as e:
                    logger.debug(f"I2P: error reading stdout: {e}")
                    break
                    
        def read_stderr():
            while self._process and self._running:
                try:
                    line = self._process.stderr.readline()
                    if not line:
                        break
                    logger.debug(f"I2P: i2pd stderr: {line.rstrip()}")
                except Exception as e:
                    logger.debug(f"I2P: error reading stderr: {e}")
                    break
                    
        self._output_thread = threading.Thread(target=read_stdout, daemon=True, name="i2p-stdout")
        self._output_thread.start()
        
        stderr_thread = threading.Thread(target=read_stderr, daemon=True, name="i2p-stderr")
        stderr_thread.start()

    def _wait_for_sam(self):
        """
        Background thread: polls SAM bridge until it's up or timeout.
        Sets self._available = True when ready.
        i2pd typically takes 2-5 minutes on first run to build tunnels.
        """
        logger.info(f"I2P: monitoring SAM bridge (up to {SAM_STARTUP_TIMEOUT}s)...")
        deadline = time.time() + SAM_STARTUP_TIMEOUT
        attempts = 0
        while time.time() < deadline and self._running:
            attempts += 1
            if self._sam_reachable():
                self._available = True
                logger.info("I2P: SAM bridge is up — internet peer discovery enabled")
                return
            
            # Log process status periodically
            if attempts % 6 == 0:  # Every 30 seconds
                process_status = self._get_process_status()
                logger.debug(f"I2P: periodic check - {process_status}")
                
            time.sleep(5)
            
        if not self._available:
            process_status = self._get_process_status()
            logger.warning(
                f"I2P: SAM bridge not ready after {SAM_STARTUP_TIMEOUT} seconds.\n"
                f"  Process status: {process_status}\n"
                "  i2pd may still be building tunnels. Check i2pd output for details."
            )

    def _get_process_status(self) -> str:
        """Get detailed process status for debugging"""
        if not self._process:
            return "No i2pd process"
            
        try:
            self._process.poll()
            if self._process.returncode is None:
                return f"Running (pid: {self._process.pid})"
            else:
                return f"Exited with code: {self._process.returncode}"
        except Exception as e:
            return f"Error checking process: {e}"

    def _sam_reachable(self) -> bool:
        """Check if the i2pd SAM bridge is accepting connections."""
        try:
            with socket.create_connection((SAM_HOST, SAM_PORT), timeout=2):
                return True
        except ConnectionRefusedError:
            logger.debug(f"I2P: SAM bridge not reachable on {SAM_HOST}:{SAM_PORT} (Connection refused)")
            return False
        except TimeoutError:
            logger.debug(f"I2P: SAM bridge not reachable on {SAM_HOST}:{SAM_PORT} (Timeout)")
            return False
        except OSError as e:
            logger.debug(f"I2P: SAM bridge not reachable on {SAM_HOST}:{SAM_PORT}: {e}")
            return False
        except Exception as e:
            logger.debug(f"I2P: SAM bridge check failed: {e}")
            return False

    # ------------------------------------------------------------------ #
    # Reticulum config patching
    # ------------------------------------------------------------------ #

    def _patch_rns_config(self):
        """
        Add an I2PInterface section to ~/.reticulum/config if not present.

        Reticulum config uses an INI-like format with nested sections.
        We read the file as text and append the interface block if the
        section name doesn't already exist — avoids parsing the custom
        nested format which configparser doesn't handle cleanly.
        """
        config_path = Path(RNS_CONFIG_PATH)
        if not config_path.exists():
            logger.warning(f"I2P: Reticulum config not found at {config_path}")
            return

        content = config_path.read_text()

        # Already configured?
        if RNS_I2P_SECTION in content:
            logger.debug("I2P: Reticulum config already has I2P interface")
            return

        i2p_block = f"""
  [[{RNS_I2P_SECTION}]]
    type = I2PInterface
    enabled = yes
    peers = []

"""
        # Append after the [interfaces] section opener
        if "[interfaces]" in content:
            content = content.replace(
                "[interfaces]",
                "[interfaces]" + i2p_block,
                1
            )
            config_path.write_text(content)
            logger.info(
                "I2P: added I2PInterface to ~/.reticulum/config\n"
                "  Reticulum will use I2P on next startup."
            )
        else:
            logger.warning("I2P: could not find [interfaces] in Reticulum config")
