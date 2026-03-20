# src/vendor — Bundled Python Dependencies

This directory contains all Python packages that Personal Cloud OS depends on,
copied directly from their installed locations. No `pip install` or internet
connection is required on the target machine.

## Why vendor?

The core design principle of this project is:

    git clone → python3 main.py --cli → fully running node

No package manager. No internet. No install steps. On any modern Linux.

Vendoring achieves this by shipping the dependencies inside the repository.
`src/main.py` inserts this directory at the front of `sys.path` at startup,
so Python finds these packages before looking at the system site-packages.

## What is here

| Directory | Package | Version | Type | System libs needed |
|-----------|---------|---------|------|--------------------|
| `RNS/` | Reticulum Network Stack | 1.1.4 | Pure Python | None |
| `serial/` | pyserial | 3.5 | Pure Python | None |
| `cryptography/` | cryptography | 43.0.0 | Python + Rust `.so` | `libssl.so.3`, `libz`, `libzstd` |
| `psutil/` | psutil | 7.0.0 | Python + C `.so` | `libc` only (universal) |

## What is NOT here

| Package | Reason |
|---------|--------|
| Pillow | Removed (S2) — replaced with pure-Python PNG generator in `tray/icon.py` |
| pystray | Optional (system tray only) — not required for core functionality |
| zeroconf | Removed (S1) — was never imported anywhere |
| aiohttp | Removed (S1) — was never imported anywhere |
| colorlog | Removed (S1) — was never imported anywhere |
| prompt-toolkit | Removed (S1) — was never imported anywhere |
| PyYAML | Removed (S1) — config uses JSON |

## Compiled extensions (.so files)

Two packages have compiled C/Rust extensions:

### cryptography/_rust.abi3.so
- Built with Rust, compiled against OpenSSL
- `.abi3.so` = stable ABI, works across Python 3.2+
- Requires `libssl.so.3` and `libz.so.1` on the target system
- These are present on any Linux with OpenSSL 3.x (Ubuntu 22.04+, Debian 11+)

### psutil/_psutil_linux.abi3.so
### psutil/_psutil_posix.abi3.so
- Built with C, compiled against libc only
- `.abi3.so` = stable ABI, works across Python 3.2+
- No system library dependencies beyond libc (universal)

## How to update a package

If you need to update a vendored package to a new version:

1. Install the new version: `pip install packagename==x.y.z`
2. Find the new install location: `python3 -c "import pkg; print(pkg.__file__)"`
3. Delete the old vendor directory: `rm -rf src/vendor/packagename/`
4. Copy the new version: `cp -r /path/to/new/version src/vendor/packagename/`
5. Update the version in this README
6. Run `python3 src/verify.py` to confirm everything works
7. Commit: `git add src/vendor/ && git commit -m "vendor: update packagename to x.y.z"`

## How sys.path works

`src/main.py` contains at the very top (before any other imports):

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'vendor'))
```

This means:
- If a package is in `vendor/`, that version is used
- If a package is NOT in `vendor/`, Python falls back to system site-packages
- System packages are never completely blocked — only shadowed

## Relationship to src/bin/

`src/bin/` contains compiled binaries (currently: `i2pd`).
`src/vendor/` contains Python packages.
Together they make the app fully self-contained.

## Platform notes

The `.so` files in `cryptography/` and `psutil/` are built for `x86_64 Linux`.

For other platforms, the `.so` files need to be replaced with the appropriate
platform-specific versions:

| Platform | Action needed |
|----------|--------------|
| x86_64 Linux | Already here — works as-is |
| aarch64 Linux (Pi) | Replace `.so` files with ARM64 builds |
| Windows | Replace `.so` files with `.pyd` files |
| macOS | Replace `.so` files with `.dylib` files |

The pure-Python packages (`RNS/`, `serial/`) work unchanged on all platforms.

## Git and large files

The vendor directory is committed to git. Total size is approximately 10MB.
The compiled `.so` files are the largest components (~5MB for cryptography).

If the repo becomes too large, consider git-lfs for the `.so` files.
For now, 10MB is acceptable and keeps the repo self-contained.
