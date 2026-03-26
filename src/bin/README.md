# src/bin — Bundled Binaries

This directory contains compiled binaries that the app depends on.
They are committed to the repository so no installation is needed.

## Contents

| File | What | Version | Built for | Build step |
|------|------|---------|-----------|-----------|
| `i2pd` | I2P daemon (internet tunneling) | 2.59.0 | x86_64 Linux (static) | See BUILD.md |
| `../container/rootfs` | Alpine Linux (busybox + musl) | 3.20 | x86_64 Linux | Bundled in repo (see src/container/rootfs/) |

## i2pd

i2pd is the C++ implementation of the I2P anonymous network router.
Personal Cloud OS uses it to enable internet-routed peer discovery
without any central server, VPN provider, or static IP.

### Why a static binary?

A static binary links all C++ libraries (libboost, libssl, libstdc++) 
directly into the executable. The result has no system library
dependencies and runs on any x86_64 Linux regardless of distro or
what's installed.

### How it was built

```bash
# One-time build on the desktop machine
sudo apt install cmake libboost-dev libboost-program-options-dev \
                 libboost-filesystem-dev libboost-chrono-dev \
                 libboost-thread-dev libboost-iostreams-dev

cd /home/jonathan/project
git submodule add https://github.com/PurpleI2P/i2pd src/vendor/i2pd-src
cd src/vendor/i2pd-src
make USE_STATIC=yes USE_AESNI=yes
cp i2pd ../../bin/i2pd
chmod +x ../../bin/i2pd
```

### Platform notes

| Platform | Status | Action |
|----------|--------|--------|
| x86_64 Linux | ✅ Committed | Works as-is |
| aarch64 Linux (Pi) | ⬜ Not yet | Cross-compile or build on Pi |
| Windows | ⬜ Not yet | Use i2pd Windows release binary |
| macOS | ⬜ Not yet | Build from source on Mac |

### i2pd source

The i2pd source is included as a git submodule at `src/vendor/i2pd-src/`.
License: BSD 3-Clause (https://github.com/PurpleI2P/i2pd/blob/openssl/LICENSE)

To update to a newer version:
```bash
cd src/vendor/i2pd-src
git fetch && git checkout <new-tag>
make clean && make USE_STATIC=yes USE_AESNI=yes
cp i2pd ../../bin/i2pd
git add ../../bin/i2pd src/vendor/i2pd-src
git commit -m "vendor: update i2pd to <new-version>"
```

---

## ../container/rootfs

The Alpine Linux rootfs is bundled in the repository at `src/container/rootfs/`.
This provides the "Guest OS" layer - a minimal Alpine environment with busybox.

### Contents
- busybox (ls, cat, sh, etc. - all in one binary)
- musl libc (lightweight alternative to glibc)
- apk (Alpine package manager)
- Basic filesystem structure

### No build step needed
The rootfs is committed directly to the repo as a pre-built tarball.
When PCOS first runs, it copies this to `~/.local/share/pcos/container/rootfs/`.

### Why Alpine?
- Tiny (8MB rootfs vs 100MB+ for full distro)
- busybox means single binary for all CLI tools
- musl is smaller and faster than glibc
- apk is a simple, fast package manager
