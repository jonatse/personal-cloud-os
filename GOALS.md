# Personal Cloud OS — Goals & Priority Tracking

Last updated: 2026-03-19

This file tracks what is being worked on, what is done, and what comes next.
It is the sprint board. SPEC.md is the design document.

---

## Current State (as of 2026-03-19)

The system boots, joins the LAN via Reticulum, discovers peers, and shows
everything in a live curses CLI. Two devices (debian desktop + pop-osmark laptop)
are discovering each other successfully.

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
- [ ] **P1.4** Fix `create_link()` — store `RNS.Destination` not `RNS.Identity` in `ReticulumPeer.destination` (Bug B2)
- [ ] **P1.5** Fix `stop()` guard in ReticulumPeerService (Bug B1)
- [ ] **P1.6** Verify encrypted link establishment end-to-end (send a test message peer→peer)
- [ ] **P1.7** Add phone/Sideband discovery via Tailscale TCP interface

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

- [x] **P3.1** `SyncEngine` scans local `~/Sync` directory on startup
- [x] **P3.2** File manifest structure defined (`FileInfo` dataclass)
- [x] **P3.3** JSON wire protocol defined (6 message types)
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

