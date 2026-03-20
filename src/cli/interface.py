"""
Interactive CLI Interface for Personal Cloud OS.

Layout:
┌──────────────────────────────────────────────────────────┐
│  Personal Cloud OS  │  hostname  │  Identity: abcd...    │  ← single title bar
├──────────────────────────────────────────────────────────┤
│                                                          │
│  (command output scrolls here)                          │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  pcos ❯ _                                                │  ← persistent prompt
└──────────────────────────────────────────────────────────┘

The title bar is one row: hostname, Reticulum status, peer count.
It refreshes every REFRESH_INTERVAL seconds without touching the scroll pane.
Type 'status' for a full status snapshot.
"""
import curses
import sys
import os
import re
import logging
import threading
import time
import socket
from collections import deque
from .commands import CommandHandler

logger = logging.getLogger(__name__)

REFRESH_INTERVAL = 5   # seconds between title bar refresh
TITLE_COLOR      = 1   # white on dark blue
PEER_OK_COLOR    = 2   # green on dark blue
PEER_WAIT_COLOR  = 3   # yellow on dark blue
OUTPUT_COLOR     = 4   # default terminal colours


class CLIInterface:
    """
    Minimal curses CLI.

    One title bar at the top (auto-refreshes).
    Scrolling output in the middle.
    Persistent prompt at the bottom.
    """

    def __init__(self, app):
        self.app             = app
        self.command_handler = CommandHandler(app)
        self.running         = False

        self._output_lines   = deque(maxlen=500)
        self._output_lock    = threading.Lock()
        self._redraw_output  = threading.Event()

        self._input_buf      = ""
        self._history        = []
        self._history_idx    = -1

        self._title_win  = None
        self._output_win = None
        self._input_win  = None

    # ------------------------------------------------------------------ #
    # Public
    # ------------------------------------------------------------------ #

    def start(self):
        """Launch the curses UI. Blocks until exit."""
        self.running = True
        try:
            curses.wrapper(self._run_curses)
        except KeyboardInterrupt:
            pass
        except Exception as e:
            import traceback
            print(f"\nCLI crashed: {e}")
            print(traceback.format_exc())
        finally:
            self.running = False
            print("\nCLI session ended.")

    def stop(self):
        self.running = False

    # ------------------------------------------------------------------ #
    # Curses setup
    # ------------------------------------------------------------------ #

    def _run_curses(self, stdscr):
        self._scr = stdscr
        self._setup_colors()
        self._build_windows()
        self._install_print_hook()

        # Background title refresh
        t = threading.Thread(target=self._title_refresh_loop, daemon=True)
        t.start()

        # Initial draw
        self._draw_title()
        self._write("  Personal Cloud OS  —  type 'help' for commands")
        self._write("")
        self._draw_output()
        self._draw_input()

        self._input_loop()
        self._uninstall_print_hook()

    def _setup_colors(self):
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(TITLE_COLOR,     curses.COLOR_WHITE,  curses.COLOR_BLUE)
        curses.init_pair(PEER_OK_COLOR,   curses.COLOR_GREEN,  curses.COLOR_BLUE)
        curses.init_pair(PEER_WAIT_COLOR, curses.COLOR_YELLOW, curses.COLOR_BLUE)
        curses.init_pair(OUTPUT_COLOR,    -1, -1)

    def _build_windows(self):
        rows, cols = self._scr.getmaxyx()

        # Title: 1 row at the very top
        self._title_win = curses.newwin(1, cols, 0, 0)
        self._title_win.bkgd(' ', curses.color_pair(TITLE_COLOR))

        # Output: everything between title and input
        out_rows = max(1, rows - 2)
        self._output_win = curses.newwin(out_rows, cols, 1, 0)
        self._output_win.scrollok(True)
        self._output_win.bkgd(' ', curses.color_pair(OUTPUT_COLOR))

        # Input: last row
        self._input_win = curses.newwin(1, cols, rows - 1, 0)
        self._input_win.bkgd(' ', curses.color_pair(OUTPUT_COLOR))
        self._input_win.nodelay(False)
        self._input_win.timeout(200)

    # ------------------------------------------------------------------ #
    # Input loop
    # ------------------------------------------------------------------ #

    def _input_loop(self):
        self._input_win.keypad(True)
        curses.curs_set(1)

        while self.running:
            if self._redraw_output.is_set():
                self._redraw_output.clear()
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
                    self._write(f"pcos ❯ {cmd}")
                    try:
                        result = self.command_handler.execute(cmd)
                    except Exception as e:
                        import traceback
                        self._write(f"  [ERROR] {e}")
                        for line in traceback.format_exc().splitlines():
                            self._write(f"  {line}")
                        result = True
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
                    self._history_idx = min(self._history_idx + 1,
                                            len(self._history) - 1)
                    self._input_buf = self._history[-(self._history_idx + 1)]
                    self._draw_input()

            elif ch == curses.KEY_DOWN:
                if self._history_idx > 0:
                    self._history_idx -= 1
                    self._input_buf = self._history[-(self._history_idx + 1)]
                elif self._history_idx == 0:
                    self._history_idx = -1
                    self._input_buf = ""
                self._draw_input()

            elif ch == curses.KEY_RESIZE:
                self._build_windows()
                self._draw_title()
                self._draw_output()
                self._draw_input()

            elif isinstance(ch, str) and ch.isprintable():
                self._input_buf += ch
                self._draw_input()

    # ------------------------------------------------------------------ #
    # Title bar
    # ------------------------------------------------------------------ #

    def _title_refresh_loop(self):
        while self.running:
            time.sleep(REFRESH_INTERVAL)
            if self.running:
                self._draw_title()
                self._draw_input()

    def _draw_title(self):
        if not self._title_win:
            return
        try:
            win = self._title_win
            cols = win.getmaxyx()[1]
            win.erase()

            ret  = getattr(self.app, 'reticulum_service', None)
            host = socket.gethostname()

            identity = "—"
            if ret and hasattr(ret, '_identity_hash'):
                identity = ret._identity_hash[:16] + "..."

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

            peer_count = len(peers)

            # Build title string
            left  = f"  pcos  │  {host}  │  {identity}"
            if peer_count:
                peer_str = "  ".join(p.name for p in peers[:3])
                if peer_count > 3:
                    peer_str += f" +{peer_count-3}"
                right = f"peers: {peer_count} ({peer_str})  "
            else:
                right = "peers: waiting...  "

            # Pad middle
            pad = cols - len(left) - len(right)
            line = left + (" " * max(1, pad)) + right

            win.addstr(0, 0, line[:cols-1], curses.color_pair(TITLE_COLOR) | curses.A_BOLD)

            # Colour the peer count portion
            peer_col = (curses.color_pair(PEER_OK_COLOR)
                        if peer_count else curses.color_pair(PEER_WAIT_COLOR))
            peer_x = cols - len(right)
            if 0 < peer_x < cols - 1:
                win.addstr(0, peer_x, right[:cols - peer_x - 1], peer_col | curses.A_BOLD)

            win.noutrefresh()
            curses.doupdate()
        except Exception as e:
            logger.debug(f"Title draw error: {e}")

    # ------------------------------------------------------------------ #
    # Output pane
    # ------------------------------------------------------------------ #

    def _write(self, text):
        """Append a plain-text line to the output buffer (thread-safe)."""
        with self._output_lock:
            clean = _strip_ansi(text)
            self._output_lines.append(clean)
        self._redraw_output.set()

    def _draw_output(self):
        if not self._output_win:
            return
        try:
            win = self._output_win
            rows, cols = win.getmaxyx()
            win.erase()
            with self._output_lock:
                visible = list(self._output_lines)[-rows:]
            for i, line in enumerate(visible):
                try:
                    win.addstr(i, 0, line[:cols - 1])
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
    # print() hook
    # ------------------------------------------------------------------ #

    def _install_print_hook(self):
        self._real_stdout = sys.stdout
        writer = self._write

        class _Redirect:
            def write(self, text):
                if text == '\n':
                    writer("")
                elif text:
                    for line in text.splitlines():
                        writer(line)
            def flush(self):
                pass
            def fileno(self):
                return 1  # pretend to be stdout fd

        sys.stdout = _Redirect()

    def _uninstall_print_hook(self):
        sys.stdout = self._real_stdout


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _strip_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*[mAJK]', '', text)


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
    CLIInterface(app).start()
    return True
