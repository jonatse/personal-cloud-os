# Personal Cloud OS — Goals & Priority Tracking

Last updated: 2026-03-19

This file tracks what is being worked on, what is done, and what comes next.
It is the sprint board. SPEC.md is the design document.

---

## Current State (as of 2026-03-20)

The system boots, joins the LAN via Reticulum, discovers peers, syncs files,
and shows everything in a live curses CLI. Two devices (debian desktop + pop-osmark
laptop) are discovering each other and syncing files successfully!

---

## Known Bugs (fix before adding new features)

These are confirmed bugs in the current codebase:

| # | Bug | File | Line | Severity |
|---|-----|------|------|----------|
| B1 | `ReticulumPeerService.stop()` has inverted guard — service never actually stops | `services/reticulum_peer.py` | 149 | High |
| B2 | `ReticulumPeer.destination` stores `RNS.Identity`, not `RNS.Destination` — `create_link()` will error at runtime | `services/reticulum_peer.py` | 303 | High |
| B3 | `get_link()` always returns None — `create_link()` never stores links in `self._links` | `services/reticulum_peer.py` | 376 | High |
| B4 | `_on_link_closed` mutates dict during iteration — `RuntimeError` | `services/peer_link.py` | 264 | High |
| B5 | `List` not imported in `peer_link.py` but used in type annotation | `services/peer_link.py` | 64 | High |
| B6 | `_signal_handler` calls `asyncio.create_task()` from sync context | `main.py` | 92 | High |
| B7 | `ContainerManager._set_state()` calls `asyncio.create_task()` from sync context | `container/manager.py` | 261 | High |
| B8 | `OutputRedirect.fileno()` uses wrong `self` (closure bug) | `cli/interface.py` | ~398 | Medium |
| B9 | `cmd_quit` does not stop background services (identical to `cmd_exit`) | `cli/commands.py` | 299 | Medium |
| B10 | `setup_logging` `level` parameter has no effect (hardcoded DEBUG internally) | `core/logger.py` | — | Low |
| B11 | File chunk reassembly broken in sync — no completion tracking, partial retransmit corrupts file | `services/sync.py` | 414 | Medium |
| B12 | `asyncio.create_task()` called in Tkinter context in launcher | `ui/launcher.py` | 423 | Medium |

---

## Priority 0 — Self-Contained (must fix to meet core design goal)

The app currently requires Docker for the container feature. This violates the
"self-contained, no external deps at runtime" design principle.

- [ ] **P0.1** Replace `container/manager.py` Docker implementation with a self-contained Linux container runtime (namespace isolation via `unshare`/`bubblewrap` or similar)
- [ ] **P0.2** Bundle all runtime dependencies into the install package
- [ ] **P0.3** Remove `docker` from requirements and all Docker subprocess calls

---

## Priority 1 — Networking Foundation ✅ / 🔧

Goal: Two devices can find each other and exchange encrypted messages.

- [x] **P1.1** Reticulum initialises without external `rnsd` daemon
- [x] **P1.2** LAN peer discovery working (both directions confirmed)
- [x] **P1.3a** Peer announces and is stored in `_peers` dict
- [x] **P1.3b** CLI shows live peer count and names
- [x] **P1.4** Fix `create_link()` — store `RNS.Destination` not `RNS.Identity` in `ReticulumPeer.destination` (Bug B2)
- [x] **P1.5** Fix `stop()` guard in ReticulumPeerService (Bug B1)
- [ ] **P1.6** Verify encrypted link establishment end-to-end (send a test message peer→peer)
- [ ] **P1.7** Add phone/Sideband discovery via Tailscale TCP interface

---

## Priority 1.5 — Device Pairing & Trust

Goal: Bidirectional trust establishment between devices on the same network.

### Flow
1. Device A announces with `type: "pairing_request"` + identity_hash
2. Device B receives, shows prompt with name + hash, user manually accepts
3. Device B announces `type: "pairing_accepted"`
4. Device A receives, shows prompt, user manually accepts
5. NOW BIDIRECTIONAL TRUST ESTABLISHED

### Implementation

- [ ] **P1.5.1** Extend app_data in announces to include:
  - `identity_hash` (full RNS identity hash for verification)
  - `device_id` (SHA256 of hostname+MAC)
  - `type`: "normal" | "pairing_request" | "pairing_accepted" | "pairing_rejected"

- [ ] **P1.5.2** Detect pairing types in `_on_announce`:
  - Fire events: `pairing.request`, `pairing.accepted`, `pairing.rejected`

- [ ] **P1.5.3** Update device_manager.py:
  - Add fields: `trusted`, `pending`, `paired_by`, `paired_at`, `expires_at`
  - `add_device()` - add as pending with 24h expiry
  - `trust_device(name)` - mark trusted, record who paired
  - `reject_device(name)` - remove pending
  - `revoke_device(name)` - remove trusted
  - `is_trusted(name)` / `is_pending(name)` - checks

- [ ] **P1.5.4** CLI commands:
  - `pair` - show pending + trusted devices
  - `pair accept <name>` - approve pending device
  - `pair reject <name>` - reject/remove pending
  - `pair revoke <name>` - revoke trusted device
  - `pair trust` - list trusted
  - `pair pending` - list pending

- [ ] **P1.5.5** Auto-prompt when pairing request received:
  - Print to CLI output: "Device 'laptop' (hash: 78e5...) wants to join mesh. Accept? (y/n)"
  - Or use `pair accept` later

- [ ] **P1.5.6** Polish:
  - Handle rejection notifications
  - Cleanup expired pendings (24h)
  - Show trust status in `peers` and `device` commands
  - Edge case: simultaneous requests → auto-accept both

---

## Priority 2 — Stable CLI

Goal: The CLI is reliable, handles all edge cases, commands do what they say.

- [x] **P2.1** Curses split-screen layout (header, scroll pane, prompt)
- [x] **P2.2** Header auto-refreshes every 5s without blinking or scrolling
- [x] **P2.3** Command crashes show in output pane, don't kill the app
- [x] **P2.4** Arrow key command history
- [ ] **P2.5** Fix `cmd_quit` to actually stop background services (Bug B9)
- [ ] **P2.6** Implement `cmd_start` / `cmd_stop` / `cmd_restart` for real
- [ ] **P2.7** Fix `OutputRedirect.fileno()` closure bug (Bug B8)
- [ ] **P2.8** Add `logs` command to tail the app log from inside the CLI

---

## Priority 3 — File Sync

Goal: Files in `~/Sync` on one device appear on other devices.

- [x] **P3.1** `SyncEngine` scans local `~/Sync` directory on startup ✅ WORKING
- [x] **P3.2** File manifest structure defined (`FileInfo` dataclass) ✅ WORKING
- [x] **P3.3** JSON wire protocol defined (6 message types) ✅ WORKING
- [ ] **P3.4** Fix P2P link establishment first (P1.4–P1.6 must be done)
- [ ] **P3.5** Fix file chunk reassembly (Bug B11)
- [ ] **P3.6** Implement conflict resolution (newest/oldest/manual — currently always overwrites)
- [ ] **P3.7** Handle `SYNC_MSG_DELETE_FILE` (defined in protocol, not handled)
- [ ] **P3.8** Replace hex encoding with binary or base64 for file chunks
- [ ] **P3.9** Add progress indicator in CLI during file transfer

---

## Priority 4 — User Identity & Multi-Device Auth

Goal: A user has one identity that spans all their devices.

- [ ] **P4.1** Design user identity model (separate from device identity)
- [ ] **P4.2** Key exchange / trust establishment between devices
- [ ] **P4.3** Authorisation: which devices can sync to which
- [ ] **P4.4** Revocation

---

## Priority 5 — Shared Linux Environment (Phase 3 from SPEC)

- [ ] Self-contained Alpine/Debian container (depends on P0)
- [ ] SSH access to container from any device on the mesh
- [ ] Shared home directory across devices (depends on P3)
- [ ] GPU passthrough (NVIDIA RTX 4080 SUPER on desktop)
- [ ] Audio passthrough

---

## Shelved / Deferred

| Item | Reason |
|------|--------|
| `ui/launcher.py` Tkinter GUI | Not wired to main.py; no active development |
| `ui/components.py` widgets | Not used by launcher |
| Two-layer discovery service | Race condition — see `shelf/discovery.py` |
| YAML config support | requirements.txt lists PyYAML but it's never used; config is JSON |

---

## Architecture Decisions Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-03-18 | Switched from UDP broadcast discovery to Reticulum | ZeroTrust, works over any interface, identity-based |
| 2026-03-19 | Removed `PeerDiscoveryService` layer | Two-layer architecture caused race conditions; single Reticulum layer is simpler |
| 2026-03-19 | Curses split-screen CLI | Print-based refresh caused scroll spam and no persistent prompt |


---

## Priority 0.5 — Self-Contained Package (The Foundation)

**Goal**: `git clone` → `python3 main.py --cli` — works on any modern Linux
with zero internet, zero package manager, zero install steps.

**Why this comes before everything else**: Every feature we build on top
is worthless if the app can't be distributed and run offline. This is the
foundation of the decentralization vision.

**Context**: See SPEC.md "Self-Containment Architecture" section for full
technical rationale and dependency audit.

### Step-by-Step Todo List

- [ ] **S1** Clean `requirements.txt`
      Remove 5 packages that are imported nowhere in the codebase:
      `zeroconf`, `aiohttp`, `colorlog`, `prompt-toolkit`, `PyYAML`
      Keep: `rns`, `cryptography`, `pyserial`, `psutil`, `Pillow` (optional), `pystray` (optional)

- [x] **S2** Drop Pillow as a hard dependency
      Pillow is only used to draw a 16x16 tray icon in `tray/system_tray.py`.
      Replace with a pure-Python XBM/base64 icon or just skip the icon.
      This removes 3.4MB of package + 12 system library dependencies.

- [x] **S3** Create `src/vendor/` directory structure
      ```
      src/vendor/
      ├── README.md        ← documents what is here and why
      ├── RNS/             ← Reticulum (pure Python, copy as-is)
      ├── serial/          ← pyserial (pure Python, copy as-is)
      ├── cryptography/    ← includes _rust.abi3.so (needs libssl on system)
      └── psutil/          ← includes _psutil_linux.abi3.so (needs only libc)
      ```

- [x] **S4** Copy packages into `src/vendor/`
      - RNS from `/home/jonathan/.local/lib/python3.13/site-packages/RNS`
      - serial from `/home/jonathan/.local/lib/python3.13/site-packages/serial`
      - cryptography from `/usr/lib/python3/dist-packages/cryptography`
      - psutil from `/usr/lib/python3/dist-packages/psutil`

- [x] **S5** Update `src/main.py` to use vendor/ first
      Add at the very top of main.py (before any other imports):
      ```python
      import sys, os
      sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'vendor'))
      ```
      This means vendored packages are used instead of system packages.
      Falls back to system if vendor copy is missing (graceful degradation).

- [x] **S6** Install build dependencies on desktop (one time only)
      ```bash
      sudo apt install cmake libboost-dev libboost-program-options-dev \
                       libboost-filesystem-dev libboost-chrono-dev \
                       libboost-thread-dev libboost-iostreams-dev
      ```
      These are only needed on the build machine (desktop). Nobody else
      needs them. After step S7 they can be removed.

- [x] **S7** Build static i2pd binary
      ```bash
      cd /home/jonathan/project
      git submodule add https://github.com/PurpleI2P/i2pd src/vendor/i2pd-src
      cd src/vendor/i2pd-src
      make USE_STATIC=yes USE_AESNI=yes
      cp i2pd ../../bin/i2pd
      ```
      Commit `src/bin/i2pd` to the repo. This is a ~15MB binary that
      works on any x86_64 Linux with no system dependencies.
      NOTE: Also need ARM builds for Raspberry Pi (aarch64).
      ARM build can be done on a Pi or via cross-compilation.

- [x] **S8** Update `src/services/i2p_manager.py` to use bundled binary
      Change `_find_i2pd()` to check `src/bin/i2pd` FIRST before PATH.
      ```python
      # Check bundled binary first
      bundled = os.path.join(os.path.dirname(__file__), '..', 'bin', 'i2pd')
      bundled = os.path.abspath(bundled)
      if os.path.isfile(bundled) and os.access(bundled, os.X_OK):
          return bundled
      ```

- [x] **S9** Write `src/verify.py` — startup self-check
      Run on every startup, checks:
      - Python >= 3.10
      - vendor/ packages present and importable
      - src/bin/i2pd present and executable
      - libssl available on system (required for cryptography)
      - Prints a clear report: what's OK, what's missing, what to do

- [x] **S10** Test on laptop with zero pre-installed packages
      ```bash
      # On laptop - verify it works with ONLY what's in the repo
      cd ~/Projects/personal-cloud-os
      git pull
      python3 src/main.py --cli
      # Should start with zero errors, zero installs needed
      ```

- [x] **S11** PyInstaller build (makes a distributable folder)
      ```bash
      pip install pyinstaller  # only on build machine
      cd /home/jonathan/project
      pyinstaller --onedir --name pcos src/main.py
      # dist/pcos/ is a complete self-contained app folder
      # zip it, send it to anyone, it just works
      ```

- [x] **S12** Document the build process in `BUILD.md`
      One file that explains how to rebuild everything from source.
      Someone with no context should be able to read it and produce
      a working distributable.

---

## Architecture Decisions Log (continued)

| Date | Decision | Reason |
|------|----------|--------|
| 2026-03-18 | Switched from UDP broadcast discovery to Reticulum | ZeroTrust, works over any interface, identity-based |
| 2026-03-19 | Removed `PeerDiscoveryService` layer | Two-layer architecture caused race conditions; single Reticulum layer is simpler |
| 2026-03-19 | Curses split-screen CLI | Print-based refresh caused scroll spam and no persistent prompt |
| 2026-03-19 | Chose I2P (i2pd) for internet tunneling | Decentralized, no central server, open source, already integrated in Reticulum |
| 2026-03-19 | Chose vendor bundling over system packages | Self-contained, offline-first, no package manager needed on target machine |
| 2026-03-19 | Chose PyInstaller for distribution | Bundles Python + all deps into one folder, works on Linux/Windows/Mac |
| 2026-03-19 | Deferred Android until Linux is self-contained | BeeWare Briefcase for Android once core is stable; TCP interface replaces AutoInterface on mobile |
| 2026-03-19 | Desktop acts as Reticulum transport node | Always-on node routes for mobile/lightweight clients that can't do UDP multicast |
