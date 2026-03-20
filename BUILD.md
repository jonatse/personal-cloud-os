# Personal Cloud OS — Build Guide

This document explains how to reproduce every build artifact in this
repository from source. A new developer with a fresh machine should be
able to follow this guide and produce an identical result.

---

## What Needs Building

| Artifact | Location | Built on | Frequency |
|----------|----------|----------|-----------|
| `src/bin/i2pd` | Committed to repo | Ubuntu 22.04 (Jammy) | Once, or when updating i2pd |
| `dist/pcos/` | Gitignored, built locally | Any supported Linux | Each release |

Everything else (`src/vendor/`, app Python code) is committed as-is
and requires no build step.

---

## The Golden Rule

> **Always build binaries on the OLDEST supported Linux.**
>
> A binary compiled against glibc 2.35 (Ubuntu 22.04) runs on any
> Linux with glibc ≥ 2.35. A binary compiled against glibc 2.41
> (Debian trixie) fails on Ubuntu 22.04 with "GLIBC_2.38 not found".
>
> Our minimum baseline is **Ubuntu 22.04 LTS (Jammy, glibc 2.35)**.
> Use the laptop (Pop!_OS 22.04) as the build machine for binaries.

---

## Part 1 — Build `src/bin/i2pd` (static i2pd daemon)

This only needs to be done when:
- Setting up a new machine from scratch
- Updating i2pd to a new version

### 1.1 — Install build dependencies (Ubuntu 22.04 / Jammy)

```bash
sudo apt-get install -y \
    build-essential \
    cmake \
    libboost-dev \
    libboost-program-options-dev \
    libssl-dev \
    zlib1g-dev
```

**Note:** On Debian trixie (OpenSSL 3.5+) you also need `libzstd-dev`
because libcrypto.a references ZSTD symbols. On Ubuntu 22.04 (OpenSSL 3.0)
it is not needed.

### 1.2 — Clone i2pd source

```bash
git clone --depth=1 --branch 2.59.0 \
    https://github.com/PurpleI2P/i2pd.git \
    /tmp/i2pd-build
```

### 1.3 — Build

```bash
cd /tmp/i2pd-build

SYS=$(g++ -dumpmachine)           # e.g. x86_64-linux-gnu
LIBDIR="/usr/lib/$SYS"

make USE_STATIC=yes USE_UPNP=no DEBUG=no -j$(nproc) \
    LDLIBS="$LIBDIR/libboost_program_options.a \
            $LIBDIR/libssl.a \
            $LIBDIR/libcrypto.a \
            $LIBDIR/libz.a \
            -lpthread -ldl"
```

On Debian trixie add `$LIBDIR/libzstd.a` before `-lpthread`.

### 1.4 — Verify the binary

```bash
./i2pd --version
# Expected: i2pd version 2.59.0 (0.9.68)

# Check glibc requirements — must be <= 2.35 for cross-distro compat
objdump -p i2pd | grep GLIBC | sort -V | tail -3
# Must not show GLIBC_2.36 or higher

ldd i2pd
# Should only show: libstdc++, libm, libgcc_s, libc, ld-linux
```

### 1.5 — Install into the repo

```bash
cp /tmp/i2pd-build/i2pd /path/to/personal-cloud-os/src/bin/i2pd
chmod +x /path/to/personal-cloud-os/src/bin/i2pd
cd /path/to/personal-cloud-os
git add src/bin/i2pd
git commit -m "vendor: update i2pd to 2.59.0"
git push
```

### 1.6 — To update to a new i2pd version

Replace `2.59.0` in the clone command with the new tag from
https://github.com/PurpleI2P/i2pd/releases and repeat steps 1.2–1.5.

---

## Part 2 — Vendor Python packages (`src/vendor/`)

This only needs to be done when:
- Adding a new Python dependency
- Updating an existing vendored package

### 2.1 — Install the package normally first

```bash
pip install packagename==x.y.z
```

### 2.2 — Find where it was installed

```bash
python3 -c "import packagename; print(packagename.__file__)"
# e.g. /home/user/.local/lib/python3.13/site-packages/packagename/__init__.py
```

### 2.3 — Copy to vendor/

```bash
rsync -a --exclude="__pycache__" --exclude="*.pyc" --exclude="*.pyo" \
    /path/to/installed/packagename/ \
    src/vendor/packagename/
```

### 2.4 — Verify it imports from vendor

```bash
cd src/
python3 -c "
import sys, os
sys.path.insert(0, 'vendor')
import packagename
print('from vendor:', 'vendor' in packagename.__file__)
"
```

### 2.5 — Update src/vendor/README.md version table

Edit the version, type, and system libs columns for the updated package.

### 2.6 — Commit

```bash
git add src/vendor/packagename/
git commit -m "vendor: update packagename to x.y.z"
```

### Current vendored packages

| Package | Version | Notes |
|---------|---------|-------|
| `RNS` | 1.1.4 | Pure Python — Reticulum network stack |
| `serial` | 3.5 | Pure Python — serial port support |
| `cryptography` | 43.0.0 | Has `_rust.abi3.so` — needs `libssl.so.3` |
| `psutil` | 7.0.0 | Has `_psutil_linux.abi3.so` — needs only libc |

### Notes on compiled extensions (.so files)

- `.abi3.so` files use Python's stable ABI — work across Python 3.2+
- When updating `cryptography`, copy the `.so` from the same OS/arch
  you're targeting (x86_64 Linux `.so` won't work on ARM)
- For ARM (Raspberry Pi): install on the Pi, copy `.so` files from there

---

## Part 3 — PyInstaller distribution bundle (`dist/pcos/`)

Produces a self-contained 54MB folder that runs on any x86_64 Linux
with glibc ≥ 2.35. No Python required on the target machine.

### 3.1 — Install PyInstaller (build machine only)

```bash
pip install pyinstaller --break-system-packages
# or in a venv: pip install pyinstaller
```

### 3.2 — Build

```bash
cd /path/to/personal-cloud-os
pyinstaller pcos.spec -y
```

Output: `dist/pcos/`

### 3.3 — Verify

```bash
cd dist/pcos/
./pcos --help
./_internal/bin/i2pd --version
```

### 3.4 — Distribute

```bash
cd dist/
tar -czf pcos-2026-03-19-x86_64.tar.gz pcos/
# Send pcos-*.tar.gz to anyone — they just untar and run ./pcos/pcos --cli
```

### 3.5 — Rebuild triggers

Rebuild `dist/pcos/` when:
- Any Python source file in `src/` changes
- `src/bin/i2pd` is updated
- `src/vendor/` packages are updated
- `pcos.spec` is updated

The `dist/` directory is gitignored — it is not committed to the repo.
Only `pcos.spec` is committed (the recipe, not the output).

---

## Part 4 — Android (future, not yet implemented)

See GOALS.md Phase 3 — Android for the plan. Uses BeeWare Briefcase
once the Linux version is stable.

---

## Part 5 — Running verify.py

After any build step, confirm everything is in order:

```bash
# Full report
python3 src/verify.py

# Quick check (only show failures)
python3 src/verify.py --quiet

# CI-friendly (exit code 1 on failure)
python3 src/verify.py --strict
```

Expected output on a clean system:
```
  All 18 checks passed.
  git clone → python3 main.py --cli is fully self-contained.
```

---

## Dependency Decision Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-03-19 | Vendor RNS, pyserial, cryptography, psutil | Offline-first: no pip on target |
| 2026-03-19 | Remove Pillow dependency | Replace with pure-Python PNG generator — eliminates 12 system lib deps |
| 2026-03-19 | Remove zeroconf, aiohttp, colorlog, prompt-toolkit, PyYAML | Never imported anywhere in codebase |
| 2026-03-19 | Build i2pd statically on Ubuntu 22.04 | Max cross-distro compatibility (glibc 2.35 baseline) |
| 2026-03-19 | PyInstaller onedir (not onefile) | Easier to inspect, faster startup, no temp directory extraction |
| 2026-03-19 | upx=False | UPX compression triggers false positive antivirus flags |
| 2026-03-19 | console=True | CLI app, no windowed mode needed |

---

## System Requirements Summary

### To run the app (no build needed)

| Requirement | Version | Present on |
|-------------|---------|-----------|
| Python | ≥ 3.10 | Ubuntu 22.04+, Debian 11+, Pop!_OS 22.04+ |
| libssl | ≥ 3.0 | Any Linux with OpenSSL 3.x (2021+) |
| libc (glibc) | ≥ 2.35 | Ubuntu 22.04+, Debian 11+ |
| libstdc++ | ≥ 3.4.30 | Any Linux with GCC 11+ |

### To build i2pd

| Requirement | Version |
|-------------|---------|
| g++ | ≥ 11 (C++17/20 support) |
| make | any |
| libboost-program-options-dev | 1.74+ |
| libssl-dev | 3.0+ |
| zlib1g-dev | any |

### To build the PyInstaller bundle

| Requirement | Version |
|-------------|---------|
| Python | ≥ 3.10 |
| pyinstaller | ≥ 6.0 |
