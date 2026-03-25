# Personal Cloud OS — Goals & Priority Tracking

Last updated: 2026-03-25

This file tracks what is being worked on, what is done, and what comes next.
It is the sprint board. SPEC.md is the design document.

---

## Current State (as of 2026-03-25)

The system boots, joins the LAN via Reticulum, discovers peers, syncs files,
shows everything in a live curses CLI, and includes an Identity & Trust System
for access control. Two devices (debian desktop + pop-osmark laptop) are 
discovering each other and syncing files successfully!

---

## Known Bugs (fix before adding new features)

These are confirmed bugs in the current codebase:

| # | Bug | File | Line | Severity |
|---|-----|------|------|----------|
| B1 | ReticulumPeerService.stop() has inverted guard | services/reticulum_peer.py | 149 | High |
| B2 | ReticulumPeer.destination stores Identity not Destination | services/reticulum_peer.py | 303 | High |
| B3 | get_link() always returns None | services/peer_link.py | 376 | High |
| B4 | _on_link_closed mutates dict during iteration | services/peer_link.py | 264 | High |
| B5 | List not imported in peer_link.py | services/peer_link.py | 64 | High |
| B6 | _signal_handler calls asyncio.create_task() from sync | main.py | 92 | High |
| B7 | ContainerManager._set_state() calls asyncio.create_task() | container/manager.py | 261 | High |
| B8 | OutputRedirect.fileno() closure bug | cli/interface.py | ~398 | Medium |
| B9 | cmd_quit does not stop background services | cli/commands.py | 299 | Medium |
| B10 | setup_logging level parameter has no effect | core/logger.py | — | Low |
| B11 | File chunk reassembly broken | services/sync.py | 414 | Medium |
| B12 | asyncio.create_task() in Tkinter context | ui/launcher.py | 423 | Medium |

---

## Priority 0 — Self-Contained

- [ ] P0.1 Replace Docker with self-contained container runtime
- [ ] P0.2 Bundle all runtime dependencies
- [ ] P0.3 Remove docker from requirements

---

## Priority 1 — Networking Foundation

Goal: Establish encrypted mesh networking using RNS, with identity-based trust.

### Key RNS Concepts

- Identity = cryptographic keypair, used as network address
- Announce = broadcasts identity to network for discovery
- No ports needed = address is identity hash, not IP:port
- Encrypted by default = all traffic
- Network Identity = marks interfaces as belonging to your network

### Network Layer vs Application Layer

```
NETWORK LAYER (RNS):
  - All devices can route traffic (mesh works)
  - All devices can discover each other
  - Encryption is default

APPLICATION LAYER (PCOS):
  - Same identity = full access (your devices)
  - Circle identity = limited access (friends)
  - Unknown = minimal/no access
```

### Implementation

- [x] P1.1 Reticulum initialises without rnsd daemon
- [x] P1.2 LAN peer discovery working
- [x] P1.3 Peer announces stored in _peers dict
- [x] P1.4 Fix create_link() (Bug B2)
- [x] P1.5 Fix stop() guard (Bug B1)
- [x] P1.6 Verify encrypted link end-to-end
- [x] P1.7 Enable I2P interface

---

## Priority 1.5 — Identity & Trust System

Background: RNS natively provides identity-based networking. PCOS builds access control on top.

### How Trust Works

| Identity Type | How Obtained | Access Level |
|---------------|--------------|--------------|
| Personal | Create once, copy to YOUR devices | Full: all files, GPU, services |
| Circle | Shared with group (family/friends) | Limited: shared folders, chat |
| Unknown | Never trusted | Minimal: nothing |

### Access Levels

YOUR DEVICES (share personal identity):
  - Full file sync
  - GPU compute
  - All services
  - Access to /home

FRIENDS (circle identity):
  - Shared folders sync
  - Chat
  - One-off file transfers
  - NO access to /home
  - NO GPU compute

UNKNOWN:
  - No access
  - CAN route through your mesh

### Implementation

- [x] P1.5.1 Identity CLI:
  - [x] identity create
  - [x] identity show
  - [x] identity show-qr
  - [x] identity export
  - [x] identity import

- [x] P1.5.2 QR code support (qrcode, pyzbar, opencv)

- [x] P1.5.3 Circle management:
  - [x] circle create
  - [x] circle list
  - [x] circle add
  - [x] circle remove

- [x] P1.5.4 Access control middleware

- [ ] P1.5.5 I2P integration

### Onboarding

Your new device:
  pcos identity import (paste OR scan QR)
  -> shares YOUR identity = full trust

Friend:
  pcos circle create family
  pcos circle show-qr family
  friend: pcos circle import (scan QR)
  -> limited access

---

## Priority 2 — Stable CLI

- [x] P2.1 Curses split-screen layout
- [x] P2.2 Header auto-refreshes
- [x] P2.3 Command crashes handled
- [x] P2.4 Arrow key history
- [x] P2.5 Fix cmd_quit (Bug B9)
- [x] P2.6 Implement cmd_start/stop/restart
- [ ] P2.7 Fix OutputRedirect.fileno() (Bug B8)
- [x] P2.8 Add logs command

---

## Priority 3 — File Sync

- [x] P3.1 SyncEngine scans ~/Sync ✅ WORKING
- [x] P3.2 FileInfo dataclass ✅ WORKING
- [x] P3.3 JSON wire protocol ✅ WORKING
- [ ] P3.4 Fix P2P link establishment
- [ ] P3.5 Fix chunk reassembly (B11)
- [ ] P3.6 Conflict resolution
- [ ] P3.7 Handle DELETE_FILE
- [ ] P3.8 Binary/base64 encoding
- [ ] P3.9 Progress indicator

---

## Priority 4 — Shared Linux Environment

- [ ] Self-contained container (P0)
- [ ] GPU passthrough
- [ ] Shared home directory
- [ ] Distributed compute

---

## Architecture Decisions

| Date | Decision | Reason |
|------|----------|--------|
| 2026-03-18 | Reticulum instead of UDP broadcast | ZeroTrust, identity-based |
| 2026-03-19 | Removed PeerDiscoveryService layer | Race conditions |
| 2026-03-19 | Curses split-screen CLI | Scroll spam |
| 2026-03-19 | I2P for internet | Decentralized |
| 2026-03-19 | Vendor bundling | Self-contained |
| 2026-03-20 | Identity 1.5 = RNS native + PCOS access control | Simplified |
