# GOALS.md - Priority Tracking Document
# See SPEC.md for the full design specification

This document tracks what we are currently WORKING ON and what needs to be done next.

---

# Personal Cloud OS - Project Goals

## Design Requirements

### Offline-First
- Must work WITHOUT internet (offline mode)
- Must leverage internet when available
- Reticulum provides this capability over local network

### Self-Contained Packaging
- All dependencies bundled in package
- No external downloads needed at runtime
- Works on fresh Linux install without internet

---

## Goal Priority Order

### PHASE 1: Networking Foundation (CURRENT)
**Goal**: Establish working network between devices

- [x] **P1.1**: Fix Reticulum peer discovery bugs in reticulum_peer.py
  - Bug: `_handle_announce` uses undefined `destination` instead of `announced_destination`
  - Bug: Threading issue - `asyncio.create_task` called from non-async context
  - Add missing `reticulum` config section

- [ ] **P1.2**: Ensure both devices can see each other on local network
  - Both devices run app with Reticulum
  - Peer discovery shows both devices

- [ ] **P1.3**: Verify network connectivity between devices
  - Can establish encrypted link between devices
  - Can send/receive test messages

### PHASE 2: User Identity Management
**Goal**: Know which devices belong to which user

- [ ] **P2.1**: Implement user identity system
  - Each user has unique identity (Reticulum identity)
  - Same user = trust for file sharing
  - Different users = no automatic trust

- [ ] **P2.2**: Device identity per device
  - Each device has unique device identity
  - Device identity linked to user identity
  - Shows device name in peer list

- [ ] **P2.3**: Trust verification
  - Devices with same user identity = trusted peers
  - Devices with different user identity = untrusted

### PHASE 3: Shared Linux Environment
**Goal**: Files and environment shared between user's devices

- [ ] **P3.1**: File sync between trusted peers
  - Automatic sync of designated directories
  - End-to-end encrypted
  - Conflict resolution

- [ ] **P3.2**: Container environment (future goal)
  - Shared Linux environment accessible on all devices
  - SSH access to container
  - Persistent storage

### PHASE 4: GUI Capability (FUTURE)
**Goal**: Optional graphical interface

- [ ] **P4.1**: System tray icon
- [ ] **P4.2**: Optional GUI management interface

---

## Current Status

- **Phase**: 1 (Networking Foundation)
- **P1.1**: Complete (bugs fixed)
- Need to test

## Next Steps

1. [IN PROGRESS] Test peer discovery on both devices
2. Verify network connectivity between devices
3. Continue to Phase 2: User Identity Management
