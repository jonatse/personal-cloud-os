# Personal Cloud OS — Design Specification

Version: 1.0 (updated 2026-03-19 to reflect actual implementation)

This document describes what the system IS and HOW it works.
GOALS.md tracks what is being built next.

---

## Vision

A self-contained, offline-first personal operating environment that:

- Runs as a background service on any Linux device
- Discovers other devices owned by the same user automatically — no configuration
- Creates a shared, encrypted mesh between those devices
- Eventually: shares compute resources, files, and a unified Linux environment across all devices
- Requires no cloud accounts, no central servers, no port-forwarding

---

## Current Architecture

### Layer Model

```
┌─────────────────────────────────────────────────────────┐
│                   User Interface Layer                  │
│   CLIInterface (curses)  │  SystemTray  │  AppLauncher  │
│                          │  (optional)  │  (future)     │
└──────────────────────────┼──────────────────────────────┘
                           │ commands / events
┌──────────────────────────┼──────────────────────────────┐
│                  Application Layer                      │
│   SyncEngine  │  ContainerManager  │  DeviceManager    │
└──────────────────────────┼──────────────────────────────┘
                           │ events (EventBus)
┌──────────────────────────┼──────────────────────────────┐
│                  Networking Layer                       │
│           ReticulumPeerService                          │
│   ┌─────────────────────────────────────────────────┐  │
│   │  RNS Identity  │  Destination  │  AnnounceHandler│  │
│   │  _announce_loop (thread)                        │  │
│   │  _peers dict   │  EventBus.publish               │  │
│   └─────────────────────────────────────────────────┘  │
│           PeerLinkService (WIP)                         │
│   ┌─────────────────────────────────────────────────┐  │
│   │  RNS.Link management  │  send/receive callbacks  │  │
│   └─────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────┐
│               Reticulum Network Stack (RNS)             │
│   AutoInterface (UDP multicast — LAN)                   │
│   Future: TCPClientInterface, TCPServerInterface        │
│   Future: Tailscale interface                           │
└─────────────────────────────────────────────────────────┘
```

### Event Flow

```
Reticulum announce received
    → ReticulumPeerService._handle_announce()
    → self._peers[hash] = ReticulumPeer(...)
    → EventBus.publish("peer.discovered", peer.to_dict())
        → SyncEngine._on_peer_discovered()   (registers data callback)
        → [future: other subscribers]
```

---

## Module Reference

### `src/main.py` — Orchestrator

Entry point and service wiring. `PersonalCloudOS` creates all services and
manages the asyncio event loop.

**Start order:** Reticulum → Container → PeerLink → Sync

**Stop order:** Sync → PeerLink → Discovery → Reticulum → Container

**CLI flags:**
```
python3 main.py           # background service
python3 main.py --cli     # interactive curses CLI
python3 main.py --tray    # background + system tray icon
python3 main.py --status  # (stub) show status and exit
```

---

### `src/core/config.py` — Configuration

Loads `~/.config/pcos/config.json`. Dot-notation access.

```python
config = Config()
config.get("reticulum.announce_interval", 30)  # → int
config.set("sync.sync_dir", "~/Documents/Sync")
config.save()
```

**Default keys:**

| Key | Default | Description |
|-----|---------|-------------|
| `app.debug` | `false` | Enable DEBUG logging |
| `reticulum.announce_interval` | `30` | Seconds between peer announcements |
| `reticulum.identity_path` | `~/.reticulum/storage/identities/pcos` | Base identity path |
| `discovery.peer_timeout` | `60` | Seconds before a silent peer expires |
| `sync.sync_dir` | `~/Sync` | Directory to sync across devices |
| `sync.sync_interval` | `60` | Seconds between sync cycles |
| `sync.conflict_resolution` | `"newest"` | How to resolve conflicts: newest/oldest/manual/skip |
| `container.auto_start` | `true` | Start container on app launch |
| `container.image` | `"alpine:latest"` | Container image |
| `container.name` | `"pcos-container"` | Container name |

---

### `src/core/events.py` — Event Bus

In-process publish/subscribe. Services communicate through events, not direct calls.

```python
# Subscribe
event_bus.subscribe("peer.discovered", my_async_handler)

# Publish (two styles both work)
await event_bus.publish(Event(type="peer.discovered", data={...}, source="reticulum"))
await event_bus.publish(type="peer.discovered", data={...}, source="reticulum")

# History
event_bus.get_history("peer.discovered", limit=5)
```

**Event types:**

| Event | Published by | Data |
|-------|-------------|------|
| `peer.discovered` | ReticulumPeerService | `{id, name, status, last_seen, metadata}` |
| `peer.updated` | ReticulumPeerService | `{id, name, status, last_seen, metadata}` |
| `peer.lost` | ReticulumPeerService | `{id}` |
| `reticulum.started` | ReticulumPeerService | `{identity_hash, destination_hash}` |
| `reticulum.stopped` | ReticulumPeerService | `{}` |
| `sync.started` | SyncEngine | — |
| `sync.completed` | SyncEngine | — |
| `sync.failed` | SyncEngine | — |
| `sync.progress` | SyncEngine | — |
| `sync.conflict` | SyncEngine | — |
| `container.starting` | ContainerManager | — |
| `container.started` | ContainerManager | — |
| `container.stopped` | ContainerManager | — |
| `container.error` | ContainerManager | — |
| `system.status` | main.py | `{status: "running"}` |

---

### `src/core/device_manager.py` — Device Identity

Fingerprints this device and maintains an inventory of all known devices.

```python
mgr = DeviceManager()
mgr.register_self()           # upserts this device, detects hardware
mgr.get_my_device()           # → dict with this device's entry
mgr.get_all_devices()         # → list of all known device dicts
mgr.get_peer_devices()        # → list of non-local devices

# Key attributes after construction:
mgr.device_id    # SHA-256 derived from hostname+MAC
mgr.mac          # MAC address (no colons)
mgr.hostname     # socket.gethostname()
mgr.identity_path  # path for this device's Reticulum identity file
```

**Device inventory schema** (`src/core/device_inventory.json`):

```json
{
  "devices": {
    "hostname": {
      "name": "Human name",
      "hostname": "machine-hostname",
      "device_id": "hex string (SHA-256 of hostname+MAC)",
      "mac": "hexmac no colons",
      "is_local": true,
      "ssh": { "user": "...", "host": "...", "port": 22 },
      "project_path": "~/path/to/project",
      "identity_path": "~/.reticulum/storage/identities/pcos_XXXXXX",
      "hardware": {
        "cpu_cores": 8,
        "platform": "x86_64",
        "os": "Linux",
        "ram_total_gb": 16.0,
        "gpus": [{"name": "NVIDIA RTX ...", "vram": "16376 MiB"}]
      },
      "network": {
        "interfaces": { "eth0": ["192.168.1.x"] }
      },
      "last_updated": "2026-03-19T..."
    }
  }
}
```

> ⚠️ Never store passwords in this file. It is excluded from git via `.gitignore`.

---

### `src/services/reticulum_peer.py` — ZeroTrust Networking ★

The core networking service. This is the most important module.

**What it does:**
1. Initialises the RNS stack (no external `rnsd` required)
2. Loads or creates a device identity at `identity_path`
3. Creates a destination: `personalcloudos.peers.<identity_hash>`
4. Registers `PCOSAnnounceHandler` to receive announces matching that aspect
5. Spawns a daemon thread that re-announces every `announce_interval` seconds
6. On each incoming announce: stores/updates peer, fires `peer.discovered` or `peer.updated`

```python
service = ReticulumPeerService(config, event_bus)
await service.start()

# Get current peers
peers = service.get_peers()          # → List[ReticulumPeer]
peer  = service.get_peer(peer_id)    # → ReticulumPeer or None

# Each ReticulumPeer has:
peer.id          # hex destination hash (used as unique identifier)
peer.name        # hostname of the peer device
peer.destination # RNS.Identity object (⚠ should be RNS.Destination — bug B2)
peer.status      # PeerStatus enum
peer.last_seen   # datetime
peer.metadata    # dict

# Create an encrypted link (WIP — requires B2 fix first)
link = service.create_link(peer_id)  # → RNS.Link or None

await service.stop()
```

**Identity file location:**
```
~/.reticulum/storage/identities/pcos_<last6ofMAC>
```
Created on first run; same identity reused on every subsequent run.

---

### `src/services/peer_link.py` — Encrypted P2P Links (WIP)

Manages `RNS.Link` objects to connected peers. Currently partially functional —
link creation depends on B2 fix in `reticulum_peer.py`.

```python
svc = PeerLinkService(config, event_bus, reticulum_service)
await svc.start()

svc.connect_to_peer(peer_id)            # creates RNS.Link
svc.send_to_peer(peer_id, b"data")      # sends bytes
svc.send_text_to_peer(peer_id, "hello") # encodes and sends
svc.send_json_to_peer(peer_id, {...})   # JSON-serialises and sends
svc.broadcast(b"data")                  # sends to all connected peers → count

svc.register_data_callback(peer_id, callback)  # callback(peer_id, bytes)
svc.register_link_callback(callback)           # callback(peer_id, LinkState)

svc.is_connected_to(peer_id)   # → bool
svc.get_connected_peers()      # → List[str] (peer IDs)
svc.get_link_info(peer_id)     # → LinkInfo or None
```

---

### `src/services/sync.py` — File Sync Engine (Partial)

Syncs files in `~/Sync` between peers. Protocol is defined; transfers are partially implemented.

```python
engine = SyncEngine(config, event_bus, reticulum_service, peer_link_service)
await engine.start()   # scans ~/Sync, begins sync loop

engine.get_local_files()           # → Dict[path, FileInfo]
engine.get_remote_files(peer_id)   # → Dict[path, FileInfo]
engine.get_status()                # → SyncStatus
engine.is_running()                # → bool

await engine.sync_all()            # manual trigger: sync with all peers
await engine.add_file(filepath)    # add file to manifest
await engine.remove_file(filepath) # remove from manifest
```

**Wire protocol (JSON over RNS.Link):**

| Message type | Value | Direction | Payload |
|-------------|-------|-----------|---------|
| `REQUEST_FILELIST` | 1 | → peer | `{}` |
| `FILELIST` | 2 | ← peer | `{files: [{path, size, mtime, hash}]}` |
| `REQUEST_FILE` | 3 | → peer | `{path: "relative/path"}` |
| `FILE_DATA` | 4 | ← peer | `{path, chunk_index, data (hex), total_chunks}` |
| `FILE_COMPLETE` | 5 | ← peer | `{path}` |
| `DELETE_FILE` | 6 | → peer | `{path}` (defined, not yet handled) |

---

### `src/container/manager.py` — Container Runtime

> ⚠️ **Currently requires Docker.** This is a P0 priority to fix.

Manages an Alpine Linux container as the shared execution environment.

```python
mgr = ContainerManager(config, event_bus)
await mgr.start()    # creates + starts container if not running
await mgr.stop()     # stops container
await mgr.restart()  # stop + start

mgr.is_running()     # → bool
mgr.get_state()      # → ContainerState enum

# Run a command inside the container
stdout, stderr, rc = await mgr.execute("ls /home")

# Get shell command (does not attach — returns command list)
cmd = await mgr.get_shell()
```

---

### `src/cli/interface.py` — Curses CLI

Split-screen terminal interface. Three panels:

1. **Header** (top, fixed, 7 rows) — live stats, auto-refreshes every 5s
2. **Output pane** (middle, scrolling) — command output, last 500 lines
3. **Input line** (bottom, persistent) — prompt with command history

```python
cli = CLIInterface(app)
cli.start()   # blocks; runs until user types 'exit' or 'quit'
cli.stop()    # signal to exit (from another thread)
```

The `print()` function is intercepted while the CLI is running so that all
command output goes to the scroll pane instead of raw stdout.

---

### `src/cli/commands.py` — Command Implementations

All CLI commands are methods on `CommandHandler`. Each method:
- Takes `args: List[str]`
- Returns `bool` — `True` = keep running, `False` = exit CLI

```python
handler = CommandHandler(app)
handler.execute("peers")          # → True
handler.execute("exit")           # → False (exit signal)
handler.get_commands()            # → {name: description}
```

---

### `src/shelf/` — Archived Code

Code that has been removed from active use but kept for reference.

**`shelf/discovery.py`** — the old `PeerDiscoveryService` that sat between
`ReticulumPeerService` and the rest of the app. Removed 2026-03-19 because:
- It maintained a duplicate `_peers` dict
- Event relay between the two layers had race conditions causing peer count to always show 0
- The Reticulum service already does everything the discovery layer did

To reuse: subscribe to `peer.discovered` / `peer.updated` / `peer.lost` events
from the event bus, convert `ReticulumPeer` objects to your own data model,
add business logic (timeout, filtering, etc.), re-publish higher-level events.

---

## Design Principles

### ZeroTrust Networking
Every device identity is a cryptographic keypair. Peers are authenticated by
their identity hash — not by IP address, hostname, or any mutable network
property. All Reticulum communication is encrypted by default.

### Offline-First
The app runs fully without internet. LAN discovery works via UDP multicast
(Reticulum AutoInterface). Internet connectivity enables additional Reticulum
interfaces (TCP, Tailscale) but is never required.

### Self-Contained
All runtime dependencies should be bundled. No Docker, no external daemons,
no cloud accounts. *(Container manager currently violates this — P0 priority.)*

### Single Flat Networking Layer
There is one networking service (`ReticulumPeerService`). No discovery-over-Reticulum
abstraction layer on top. All application services query `reticulum_service` directly.
The shelved `discovery.py` explains why the two-layer approach was abandoned.

### Event-Driven
Services communicate through the `EventBus`, not by calling each other directly.
This keeps services decoupled and testable in isolation.

---

## Future Phases

### Phase 2 — Encrypted P2P Messaging
- Fix B1, B2, B3 (stop(), link creation)
- Verify link establishment and message exchange end-to-end
- Implement `cmd_start/stop/restart` for real
- Add Tailscale TCP interface for internet-routed discovery

### Phase 3 — File Sync
- Fix file chunk reassembly (B11)
- Implement conflict resolution
- Progress indicator in CLI
- Sync directory watching (inotify) instead of polling

### Phase 4 — Shared Linux Environment
- Self-contained container runtime (replaces Docker)
- SSH access to container from any peer
- Shared home directory (depends on file sync)
- GPU passthrough to container

### Phase 5 — Resource Sharing
- CPU/RAM/GPU sharing over the mesh
- Audio/video passthrough
- Remote app execution

