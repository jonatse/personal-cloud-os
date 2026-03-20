"""
Personal Cloud OS — Startup Self-Check
=======================================

Run automatically at startup (called from main.py) and also manually:

    python3 src/verify.py          # full report
    python3 src/verify.py --quiet  # only print failures
    python3 src/verify.py --strict # exit with code 1 if anything fails

Checks:
    1. Python version >= 3.10
    2. Vendored packages present and importable
    3. Compiled .so extensions load correctly
    4. System libraries required by .so files are present
    5. src/bin/i2pd present, executable, and runs
    6. Reticulum config directory exists (or can be created)
    7. App data directory writable (logs etc)

This file has ZERO imports outside stdlib so it can run before
the vendor path bootstrap in main.py.
"""
import sys
import os
import ctypes.util
import subprocess
import struct

# ── Constants ────────────────────────────────────────────────────────────────

SRC_DIR    = os.path.dirname(os.path.abspath(__file__))
VENDOR_DIR = os.path.join(SRC_DIR, 'vendor')
BIN_DIR    = os.path.join(SRC_DIR, 'bin')
# In a PyInstaller bundle, _MEIPASS points to the _internal dir
_MEIPASS = getattr(sys, '_MEIPASS', None)
if _MEIPASS:
    I2PD_BIN = os.path.join(_MEIPASS, 'bin', 'i2pd')
else:
    I2PD_BIN = os.path.join(BIN_DIR, 'i2pd')

PYTHON_MIN = (3, 10)

# Packages and the .so files they contain
VENDOR_PACKAGES = {
    'RNS':          [],                          # pure Python
    'serial':       [],                          # pure Python
    'cryptography': ['hazmat/bindings/_rust.abi3.so'],
    'psutil':       ['_psutil_linux.abi3.so', '_psutil_posix.abi3.so'],
}

# System libs needed by the .so extensions (lib name without 'lib' prefix)
REQUIRED_SYSTEM_LIBS = {
    'ssl':    'needed by cryptography/_rust.abi3.so',
    'z':      'needed by cryptography/_rust.abi3.so',
    'stdc++': 'needed by src/bin/i2pd',
    'c':      'universal C runtime',
}

# These are on modern systems but not absolute universals
PREFERRED_SYSTEM_LIBS = {
    'zstd': 'needed by cryptography on OpenSSL 3.5+ systems',
}

RESET  = '\033[0m'
BOLD   = '\033[1m'
GREEN  = '\033[32m'
YELLOW = '\033[33m'
RED    = '\033[31m'
CYAN   = '\033[36m'


# ── Check functions ───────────────────────────────────────────────────────────

def check_python_version():
    v = sys.version_info
    ok = (v.major, v.minor) >= PYTHON_MIN
    return ok, f"Python {v.major}.{v.minor}.{v.micro}", \
           f"need >= {PYTHON_MIN[0]}.{PYTHON_MIN[1]}"


def check_vendor_dir():
    exists = os.path.isdir(VENDOR_DIR)
    return exists, VENDOR_DIR, "directory missing"


def check_vendor_package(name, so_files):
    pkg_dir = os.path.join(VENDOR_DIR, name)
    init    = os.path.join(pkg_dir, '__init__.py')

    if not os.path.isdir(pkg_dir):
        return False, f"vendor/{name}/", "directory missing"
    if not os.path.isfile(init):
        return False, f"vendor/{name}/__init__.py", "missing"

    # Check .so files exist
    missing_so = []
    for so in so_files:
        so_path = os.path.join(pkg_dir, so)
        if not os.path.isfile(so_path):
            missing_so.append(so)
    if missing_so:
        return False, f"vendor/{name}/", f"missing .so: {missing_so}"

    return True, f"vendor/{name}/", ""


def check_package_importable(name):
    """Try to actually import the package from vendor."""
    # Ensure vendor is on path
    if VENDOR_DIR not in sys.path:
        sys.path.insert(0, VENDOR_DIR)
    if SRC_DIR not in sys.path:
        sys.path.insert(0, SRC_DIR)

    # Remove cached version if already imported from elsewhere
    if name in sys.modules:
        mod_path = getattr(sys.modules[name], '__file__', '') or ''
        if 'vendor' not in mod_path:
            del sys.modules[name]

    try:
        mod = __import__(name)
        mod_path = getattr(mod, '__file__', '') or ''
        from_vendor = 'vendor' in mod_path
        ver = getattr(mod, '__version__', getattr(mod, 'VERSION', '?'))
        if not from_vendor:
            return False, f"{name} v{ver}", "loaded from system, not vendor"
        return True, f"{name} v{ver}", ""
    except ImportError as e:
        return False, name, str(e)
    except Exception as e:
        return False, name, f"error: {e}"


def check_system_lib(lib_name, note):
    found = ctypes.util.find_library(lib_name)
    if found:
        return True, f"lib{lib_name} ({found})", note
    return False, f"lib{lib_name}", f"NOT FOUND — {note}"


def check_i2pd():
    if not os.path.isfile(I2PD_BIN):
        return False, I2PD_BIN, "file missing"
    if not os.access(I2PD_BIN, os.X_OK):
        return False, I2PD_BIN, "not executable (chmod +x needed)"
    try:
        r = subprocess.run(
            [I2PD_BIN, '--version'],
            capture_output=True, text=True, timeout=5
        )
        first_line = r.stdout.strip().splitlines()[0] if r.stdout.strip() else "no output"
        return True, first_line, ""
    except subprocess.TimeoutExpired:
        return False, I2PD_BIN, "timed out"
    except Exception as e:
        return False, I2PD_BIN, str(e)


def check_rns_config():
    rns_dir = os.path.expanduser("~/.reticulum")
    if os.path.isdir(rns_dir):
        return True, rns_dir, ""
    # Not there yet — will be created on first RNS init, that's fine
    return True, rns_dir, "(will be created on first run)"


def check_data_dir():
    data_dir = os.path.expanduser("~/.local/share/pcos")
    try:
        os.makedirs(data_dir, exist_ok=True)
        test_file = os.path.join(data_dir, '.write_test')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        return True, data_dir, ""
    except Exception as e:
        return False, data_dir, str(e)


# ── Reporter ─────────────────────────────────────────────────────────────────

class Report:
    def __init__(self, quiet=False):
        self.quiet   = quiet
        self.passed  = []
        self.failed  = []
        self.warned  = []

    def ok(self, label, detail=''):
        self.passed.append((label, detail))
        if not self.quiet:
            d = f"  {CYAN}{detail}{RESET}" if detail else ""
            print(f"  {GREEN}✓{RESET} {label}{d}")

    def warn(self, label, detail=''):
        self.warned.append((label, detail))
        d = f"  {YELLOW}{detail}{RESET}" if detail else ""
        print(f"  {YELLOW}⚠{RESET} {label}{d}")

    def fail(self, label, reason=''):
        self.failed.append((label, reason))
        r = f"  {RED}{reason}{RESET}" if reason else ""
        print(f"  {RED}✗{RESET} {label}{r}")

    def summary(self):
        total = len(self.passed) + len(self.failed) + len(self.warned)
        print()
        if not self.failed and not self.warned:
            if not self.quiet:
                print(f"{BOLD}{GREEN}  All {total} checks passed.{RESET}")
                print(f"  {CYAN}git clone → python3 main.py --cli{RESET} is fully self-contained.\n")
        elif not self.failed:
            print(f"{BOLD}{YELLOW}  {len(self.passed)}/{total} checks passed, "
                  f"{len(self.warned)} warnings.{RESET}")
            print(f"  App will run but some optional features may be limited.\n")
        else:
            print(f"{BOLD}{RED}  {len(self.failed)} check(s) FAILED, "
                  f"{len(self.passed)} passed.{RESET}")
            print(f"  {RED}The app may not start correctly.{RESET}\n")
            for label, reason in self.failed:
                print(f"  {RED}✗ {label}{RESET}")
                if reason:
                    print(f"    → {reason}")
            print()

    @property
    def success(self):
        return len(self.failed) == 0


# ── Main ──────────────────────────────────────────────────────────────────────

def run_checks(quiet=False):
    r = Report(quiet=quiet)

    if not quiet:
        print(f"\n{BOLD}  Personal Cloud OS — Self-Check{RESET}")
        print(f"  {'─' * 46}\n")

    # ── 1. Python version ──────────────────────────────────────────────────
    if not r.quiet: print(f"  {BOLD}Python{RESET}")
    ok, detail, reason = check_python_version()
    if ok:
        r.ok("version", detail)
    else:
        r.fail("version", f"{detail} — {reason}")
    if not r.quiet: print()

    # ── 2. Vendor directory ────────────────────────────────────────────────
    if not r.quiet: print(f"  {BOLD}Vendor packages  (src/vendor/){RESET}")
    ok, detail, reason = check_vendor_dir()
    if not ok:
        r.fail("vendor/ directory", reason)
        print(f"  {RED}Cannot continue vendor checks — vendor/ missing{RESET}\n")
    else:
        r.ok("vendor/ exists", detail)
        for name, so_files in VENDOR_PACKAGES.items():
            ok, detail, reason = check_vendor_package(name, so_files)
            if ok:
                r.ok(f"{name}/", detail)
            else:
                r.fail(detail, reason)

        print()
        if not r.quiet: print(f"  {BOLD}Import checks{RESET}")
        for name in VENDOR_PACKAGES:
            ok, detail, reason = check_package_importable(name)
            if ok:
                r.ok(f"import {name}", detail)
            else:
                r.fail(f"import {name}", reason)
    if not r.quiet: print()

    # ── 3. System libraries ────────────────────────────────────────────────
    if not r.quiet: print(f"  {BOLD}System libraries  (must exist on OS){RESET}")
    for lib, note in REQUIRED_SYSTEM_LIBS.items():
        ok, detail, reason = check_system_lib(lib, note)
        if ok:
            r.ok(detail, note)
        else:
            r.fail(detail, reason)

    for lib, note in PREFERRED_SYSTEM_LIBS.items():
        ok, detail, reason = check_system_lib(lib, note)
        if ok:
            r.ok(detail, note)
        else:
            r.warn(detail, f"optional — {note}")
    if not r.quiet: print()

    # ── 4. i2pd binary ────────────────────────────────────────────────────
    if not r.quiet: print(f"  {BOLD}I2P daemon  (src/bin/i2pd){RESET}")
    ok, detail, reason = check_i2pd()
    if ok:
        r.ok("i2pd", detail)
    else:
        r.fail("i2pd", reason)
    if not r.quiet: print()

    # ── 5. Runtime directories ────────────────────────────────────────────
    if not r.quiet: print(f"  {BOLD}Runtime directories{RESET}")
    ok, detail, reason = check_rns_config()
    if ok:
        r.ok("~/.reticulum", reason or detail)
    else:
        r.fail("~/.reticulum", reason)

    ok, detail, reason = check_data_dir()
    if ok:
        r.ok("~/.local/share/pcos", detail)
    else:
        r.fail("~/.local/share/pcos", reason)

    r.summary()
    return r


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Personal Cloud OS self-check')
    parser.add_argument('--quiet',  action='store_true',
                        help='Only print failures')
    parser.add_argument('--strict', action='store_true',
                        help='Exit with code 1 if any check fails')
    args = parser.parse_args()

    report = run_checks(quiet=args.quiet)

    if args.strict and not report.success:
        sys.exit(1)


if __name__ == '__main__':
    main()
