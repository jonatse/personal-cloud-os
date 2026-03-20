"""
Interactive CLI Interface for Personal Cloud OS.

Layout (curses split-screen):
┌──────────────────────────────────────────────────────────┐
│  HEADER (fixed, ~7 lines)  — live stats, auto-refreshes  │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  OUTPUT PANE (scrolling)  — command results appear here  │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  pcos ❯ _   (persistent input line at bottom)            │
└──────────────────────────────────────────────────────────┘

The header redraws in place every REFRESH_INTERVAL seconds.
The output pane scrolls normally. The prompt stays at the bottom.
"""
import curses
import sys
import os
import logging
import threading
import time
import socket
import textwrap
from collections import deque
from .commands import CommandHandler

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 5   # seconds between header redraws
HEADER_LINES     = 7   # rows reserved for the fixed header
OUTPUT_COLOR     = 1   # curses colour pair indices
HEADER_COLOR     = 2
PEER_OK_COLOR    = 3
PEER_WAIT_COLOR  = 4
DIM_COLOR        = 5


class CLIInterface:
    """Curses-based split-screen CLI with live header and scrolling output."""

    def __init__(self, app):
        self.app             = app
        self.command_handler = CommandHandler(app)
        self.running         = False

        # Output buffer – stores plain-text lines for the scroll pane
        self._output_lines   = deque(maxlen=500)
        self._output_lock    = threading.Lock()

        # Current input buffer
        self._input_buf      = ""
        self._input_lock     = threading.Lock()

        # Command history
        self._history        = []
        self._history_idx    = -1

        # curses windows (set inside _run_curses)
        self._scr            = None   # full screen
        self._header_win     = None   # top fixed panel
        self._output_win     = None   # scrolling middle panel
        self._input_win      = None   # single-line bottom panel

        self._needs_output_redraw = threading.Event()

    # ------------------------------------------------------------------ #
    # Entry point
    # ------------------------------------------------------------------ #

    def start(self):
        """Launch the curses UI. Blocks until the user exits."""
        self.running = True
        try:
            curses.wrapper(self._run_curses)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            import traceback
            # curses is already torn down here, safe to print normally
            print(f"\nCLI crashed: {e}")
            print(traceback.format_exc())
        finally:
            self.running = False
            print("\nCLI session ended.")

    def stop(self):
        self.running = False

    # ------------------------------------------------------------------ #
    # Curses main loop
    # ------------------------------------------------------------------ #

    def _run_curses(self, stdscr):
        self._scr = stdscr
        self._setup_colors()
        self._build_windows()

        # Intercept print() so commands write to output pane
        self._install_print_hook()

        # Start background header refresh thread
        t = threading.Thread(target=self._header_refresh_loop, daemon=True)
        t.start()

        # Initial render
        self._draw_header()
        self._write_output_line("  Personal Cloud OS — type 'help' for commands")
        self._write_output_line("")
        self._draw_output()
        self._draw_input()

        # Input loop
        self._input_loop()

        # Restore print
        self._uninstall_print_hook()

    def _input_loop(self):
        """Read keystrokes, build input buffer, execute on Enter."""
        self._input_win.keypad(True)
        curses.curs_set(1)

        while self.running:
            # Redraw output if flagged by background thread
            if self._needs_output_redraw.is_set():
                self._needs_output_redraw.clear()
                self._draw_output()
                self._draw_input()

            try:
                ch = self._input_win.get_wch()
            except curses.error:
                time.sleep(0.05)
                continue

            if ch in (curses.KEY_ENTER, '\n', '\r'):
                cmd = self._input_buf.strip()
                self._input_buf = ""
                self._history_idx = -1
                if cmd:
                    self._history.append(cmd)
                    self._write_output_line(f"pcos ❯ {cmd}")
                    try:
                        result = self.command_handler.execute(cmd)
                    except Exception as e:
                        import traceback
                        self._write_output_line(f"  [ERROR] {e}")
                        for line in traceback.format_exc().splitlines():
                            self._write_output_line(f"  {line}")
                        result = True  # don't exit on command errors
                    self._draw_output()
                    if not result:
                        self.running = False
                        break
                self._draw_input()

            elif ch in (curses.KEY_BACKSPACE, 127, '\x7f'):
                if self._input_buf:
                    self._input_buf = self._input_buf[:-1]
                self._draw_input()

            elif ch == curses.KEY_UP:
                if self._history:
                    self._history_idx = min(
                        self._history_idx + 1, len(self._history) - 1)
                    self._input_buf = self._history[
                        -(self._history_idx + 1)]
                    self._draw_input()

            elif ch == curses.KEY_DOWN:
                if self._history_idx > 0:
                    self._history_idx -= 1
                    self._input_buf = self._history[
                        -(self._history_idx + 1)]
                elif self._history_idx == 0:
                    self._history_idx = -1
                    self._input_buf = ""
                self._draw_input()

            elif ch == curses.KEY_RESIZE:
                self._build_windows()
                self._draw_header()
                self._draw_output()
                self._draw_input()

            elif isinstance(ch, str) and ch.isprintable():
                self._input_buf += ch
                self._draw_input()

    # ------------------------------------------------------------------ #
    # Window construction
    # ------------------------------------------------------------------ #

    def _build_windows(self):
        """Create / recreate the three panels after resize."""
        rows, cols = self._scr.getmaxyx()

        # Header: top HEADER_LINES rows
        self._header_win = curses.newwin(HEADER_LINES, cols, 0, 0)
        self._header_win.bkgd(' ', curses.color_pair(HEADER_COLOR))

        # Output: between header and input line
        out_rows = max(1, rows - HEADER_LINES - 1)
        self._output_win = curses.newwin(out_rows, cols, HEADER_LINES, 0)
        self._output_win.scrollok(True)
        self._output_win.bkgd(' ', curses.color_pair(OUTPUT_COLOR))

        # Input: last row
        self._input_win = curses.newwin(1, cols, rows - 1, 0)
        self._input_win.bkgd(' ', curses.color_pair(OUTPUT_COLOR))
        self._input_win.nodelay(False)
        self._input_win.timeout(200)

    def _setup_colors(self):
        curses.start_color()
        curses.use_default_colors()
        # pair(OUTPUT_COLOR)  – output pane: default on default
        curses.init_pair(OUTPUT_COLOR,  -1, -1)
        # pair(HEADER_COLOR)  – header bg: white text on dark blue
        curses.init_pair(HEADER_COLOR,  curses.COLOR_WHITE,  curses.COLOR_BLUE)
        # pair(PEER_OK_COLOR) – green text (peers connected)
        curses.init_pair(PEER_OK_COLOR, curses.COLOR_GREEN,  curses.COLOR_BLUE)
        # pair(PEER_WAIT_COLOR)– yellow text (waiting)
        curses.init_pair(PEER_WAIT_COLOR, curses.COLOR_YELLOW, curses.COLOR_BLUE)
        # pair(DIM_COLOR)     – dim text in header
        curses.init_pair(DIM_COLOR,     curses.COLOR_CYAN,   curses.COLOR_BLUE)

    # ------------------------------------------------------------------ #
    # Header drawing (runs in background thread + on resize)
    # ------------------------------------------------------------------ #

    def _header_refresh_loop(self):
        while self.running:
            time.sleep(REFRESH_INTERVAL)
            if self.running:
                self._draw_header()
                self._draw_input()   # keep cursor in right place

    def _draw_header(self):
        """Redraw the fixed header panel in place — no flicker."""
        if not self._header_win:
            return
        try:
            win = self._header_win
            win.erase()
            cols = win.getmaxyx()[1]

            ret     = getattr(self.app, 'reticulum_service', None)
            dev_mgr = getattr(self.app, 'device_manager', None)
            sync    = getattr(self.app, 'sync_engine', None)
            cont    = getattr(self.app, 'container_manager', None)

            hostname  = socket.gethostname()
            identity  = "—"
            dest      = "—"
            if ret:
                identity = getattr(ret, '_identity_hash', '—')[:20] + "..."
                dest     = getattr(ret, '_destination_hash', '—')[:20] + "..."

            peers = []
            if ret and hasattr(ret, 'get_peers'):
                try:
                    seen = set()
                    for p in ret.get_peers():
                        if p.name not in seen:
                            peers.append(p)
                            seen.add(p.name)
                except Exception:
                    pass

            sync_state = "—"
            if sync:
                try:
                    sync_state = sync.get_status().state
                except Exception:
                    pass

            net_state  = ("Online"  if ret and ret.is_running() else "Offline")
            cont_state = ("Running" if cont and cont.is_running() else "Stopped")

            # ── Row 0: title bar ──────────────────────────────────────────
            title = f"  Personal Cloud OS  │  {hostname}  │  {net_state}"
            win.addstr(0, 0, title.ljust(cols), curses.color_pair(HEADER_COLOR) | curses.A_BOLD)

            # ── Row 1: identity ───────────────────────────────────────────
            win.addstr(1, 2, "Identity : ", curses.color_pair(DIM_COLOR))
            win.addstr(identity, curses.color_pair(HEADER_COLOR))
            win.addstr("   Dest : ", curses.color_pair(DIM_COLOR))
            win.addstr(dest, curses.color_pair(HEADER_COLOR))

            # ── Row 2: peers ──────────────────────────────────────────────
            peer_count = len(peers)
            peer_color = curses.color_pair(PEER_OK_COLOR) if peer_count else curses.color_pair(PEER_WAIT_COLOR)
            win.addstr(2, 2, "Peers    : ", curses.color_pair(DIM_COLOR))
            dot = "● " if peer_count else "○ "
            win.addstr(dot, peer_color | curses.A_BOLD)
            if peer_count:
                names = "  ".join(p.name for p in peers[:4])
                if peer_count > 4:
                    names += f"  (+{peer_count-4} more)"
                win.addstr(f"{peer_count} connected  — {names}", peer_color)
            else:
                win.addstr("waiting for peers...", peer_color)

            # ── Row 3: sync / container ───────────────────────────────────
            win.addstr(3, 2, "Sync     : ", curses.color_pair(DIM_COLOR))
            win.addstr(sync_state.ljust(12), curses.color_pair(HEADER_COLOR))
            win.addstr("   Container : ", curses.color_pair(DIM_COLOR))
            win.addstr(cont_state, curses.color_pair(HEADER_COLOR))

            # ── Row 4: divider ────────────────────────────────────────────
            win.addstr(4, 0, "─" * cols, curses.color_pair(DIM_COLOR))

            # ── Row 5: hint ───────────────────────────────────────────────
            hint = "  help · peers · sync · network · device · exit · quit"
            win.addstr(5, 0, hint[:cols-1], curses.color_pair(DIM_COLOR))

            # ── Row 6: divider ────────────────────────────────────────────
            win.addstr(6, 0, "─" * cols, curses.color_pair(DIM_COLOR))

            win.noutrefresh()
            curses.doupdate()
        except Exception as e:
            logger.debug(f"Header draw error: {e}")

    # ------------------------------------------------------------------ #
    # Output pane
    # ------------------------------------------------------------------ #

    def _write_output_line(self, text):
        """Append a line to the output buffer (thread-safe)."""
        with self._output_lock:
            # Strip ANSI escapes — curses does its own colouring
            clean = self._strip_ansi(text)
            self._output_lines.append(clean)
        self._needs_output_redraw.set()

    def _draw_output(self):
        """Redraw the scrolling output pane."""
        if not self._output_win:
            return
        try:
            win = self._output_win
            rows, cols = win.getmaxyx()
            win.erase()
            with self._output_lock:
                visible = list(self._output_lines)[-(rows):]
            for i, line in enumerate(visible):
                try:
                    win.addstr(i, 0, line[:cols-1])
                except curses.error:
                    pass
            win.noutrefresh()
            curses.doupdate()
        except Exception as e:
            logger.debug(f"Output draw error: {e}")

    # ------------------------------------------------------------------ #
    # Input line
    # ------------------------------------------------------------------ #

    def _draw_input(self):
        """Redraw the prompt line and reposition the cursor."""
        if not self._input_win:
            return
        try:
            win = self._input_win
            cols = win.getmaxyx()[1]
            win.erase()
            prompt = "pcos ❯ "
            win.addstr(0, 0, prompt, curses.A_BOLD)
            win.addstr(self._input_buf[:cols - len(prompt) - 1])
            win.noutrefresh()
            curses.doupdate()
        except Exception as e:
            logger.debug(f"Input draw error: {e}")

    # ------------------------------------------------------------------ #
    # print() hook — redirect commands' print() into output pane
    # ------------------------------------------------------------------ #

    def _install_print_hook(self):
        self._real_stdout = sys.stdout
        cli = self

        class OutputRedirect:
            def write(self, text):
                if text and text != '\n':
                    for line in text.splitlines():
                        cli._write_output_line(line)
                elif text == '\n':
                    cli._write_output_line("")
            def flush(self):
                pass
            def fileno(self):
                return self._real_stdout.fileno() if hasattr(cli, '_real_stdout') else 1

        sys.stdout = OutputRedirect()

    def _uninstall_print_hook(self):
        sys.stdout = self._real_stdout

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _strip_ansi(text):
        """Remove ANSI escape codes from a string."""
        import re
        return re.sub(r'\x1b\[[0-9;]*[mAJK]', '', text)


# ------------------------------------------------------------------ #
# Open in new terminal
# ------------------------------------------------------------------ #

def open_cli(app):
    """Open the CLI in a new terminal window."""
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
            subprocess.Popen(term, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except FileNotFoundError:
            continue

    print("Could not open new terminal. Opening in current terminal...")
    CLIInterface(app).start()
    return True
