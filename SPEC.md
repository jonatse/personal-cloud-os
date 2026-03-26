# Personal Cloud OS — Design Specification

Version: 1.0 (updated 2026-03-26 to reflect actual implementation)

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

## Current Status (as of 2026-03-26)

### Working Features
- RNS networking (LAN + I2P)
- Peer discovery via announces
- File sync between devices
- Identity-based access control
- Remote command execution via Unix socket API

### Socket API
- Path: `~/.local/run/pcos/messaging.sock`
- Protocol: JSON over Unix socket
- Commands: `peers`, `execute`, `status`
- Security: File permissions 0600 (owner only)

### Known Limitation
- CLI remote command has curses issues in non-interactive mode
- Socket API provides alternative access path

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

## Key Architectural Lesson: Don't Reimplement RNS

### The Problem

Early in development, we attempted to build custom protocols on top of RNS:
- Custom packet framing and routing
- Custom link management
- Custom chunking and flow control

This created several problems:
1. **Fighting with RNS** — Our code conflicted with RNS's built-in mechanisms
2. **Race conditions** — Duplicate state between our layer and RNS caused sync issues
3. **Reinventing the wheel** — RNS already provides everything we needed natively
4. **Bloat** — Extra code that just added complexity without benefit

### The Solution

Use RNS natively:
- `link.request()` — Sends requests with built-in retry/timeout
- `destination.register_request_handler()` — Registers handlers, RNS auto-routes
- `RNS.Resource` — Handles chunking, windowing, flow control automatically
- Single link per peer — Already saturates LAN bandwidth

### What We Removed

- **PeerDiscoveryService** — Extra abstraction layer that duplicated RNS functionality
- **Custom packet routing** — No set_packet_callback, no _route_packet
- **Manual chunking** — RNS.Resource handles it

### When to Add New Protocol Features

Ask: "Does RNS already provide this?"
- If yes → Use RNS native (usually the case)
- If no → Implement carefully, keeping it minimal and focused

The mesh routing is handled by RNS. PCOS handles access control and services.

---

## Device Inventory & Self-Healing Network

### Vision

Every device in your ownership circle shares its information with other trusted devices:
- Hardware specs (CPU, RAM, GPU, storage)
- Network capabilities (LAN, I2P, WiFi, cellular)
- RNS identity (for mesh routing)
- Available services (what it can offer to the network)
- Encrypted recovery credentials (for fallback access)

### Sharing Rules

| Identity Type | What They See |
|--------------|----------------|
| Personal (same identity) | Full device inventory |
| Circle (friend/family) | Minimal (enough to route through them) |
| Unknown | Nothing |

### Self-Repair Capability

If a device breaks (software crash, misconfiguration, etc.):

1. **Primary recovery**: Other devices connect via RNS mesh to diagnose/fix
   - RNS works over LAN, I2P (internet), or mesh radio
   - No external network needed for local recovery

2. **Fallback recovery**: If RNS itself is broken (rare), use backup networks:
   - SSH (if enabled and reachable)
   - Headscale/Tailscale VPN (separate network path)
   - Any other available network interface

The fallback is for **when RNS itself is not working** — you need an independent path to reach the device to reinstall/repair RNS.

### Security Model

```
Physical access ≠ Data access
```

Even if someone steals your device and extracts the storage:
- They get the app code (replicatable, not secret)
- They don't get your files (encrypted with your identity key)
- They don't get stored credentials (encrypted, key not on device)

The device inventory itself should be encrypted so it can't be read by attackers.

### Information Pool

The shared device inventory (`~/.local/share/pcos/device_inventory.json`) becomes:
- A map of what's available in your personal cloud
- A tool for routing (knowing which device can help with what)
- A recovery resource (knowing how to reach each device)

This is different from GitHub-hosted deployment — the network heals itself.

---

## Messaging Architecture

*Added 2026-03-25 — planning document for future implementation*

### What RNS Already Provides

Reticulum provides built-in messaging primitives that PCOS can leverage directly:

| Feature | RNS API | Use Case |
|---------|---------|----------|
| Request/Response | `destination.register_request_handler(path, callback)` + `link.request(path, data)` | RPC-style commands, status queries |
| Link Callbacks | `link.set_established_callback()`, `link.set_closed_callback()`, `link.set_remote_identified_callback()` | Connection state, auth events |
| Chunked/Streamed Data | `RNS.Resource` | Large payloads, file transfers, streaming |
| Broadcast | `destination.send_broadcast(data)` | Announcements to all peers |
| Group Destinations | `RNS.Destination(type=GROUP)` | Multi-peer "circles" for chat |

All of these are already available in the existing `reticulum_peer.py` code — no new RNS features needed.

### Existing Foundation to Build On

The following PCOS components provide the foundation for messaging:

- **DeviceManager** — Maintains device inventory with hardware and network info
- **AccessControl** (conceptual) — Trust levels: personal/circle/unknown
- **ReticulumPeerService** — Already has request handlers:
  - `/sync/index` — returns file list
  - `/sync/file` — returns file data
- **IdentityManager** (conceptual) — Identity management via RNS

### Proposed Message Types

#### Command Messages

Run remote scripts, restart services, trigger sync:

```python
link.request("/cmd", {
    "action": "restart_service",
    "service": "container",
    "args": {}
})
```

Handler registers at `/cmd/execute`, returns JSON result.

#### Status Messages

Share device inventory, health metrics, capabilities:

```python
link.request("/status", {
    "what": "inventory"
})
```

Handler registers at `/status`, returns device info. Can extend for periodic broadcast.

#### Chat Messages

Simple peer-to-peer text:

```python
link.request("/chat", {
    "message": "Hello from my laptop",
    "timestamp": 1234567890
})
```

Or use GROUP destination for multi-peer conversations.

### Chat Architecture (Future PCOS App)

#### Design Goals

- **Extensible** — Bridge to other protocols later (Matrix, IRC, etc.)
- **Simple first** — Direct peer-to-peer, then GROUP destinations
- **Offline-first** — Messages queue and deliver when peers appear

#### Evolution Plan

```
P3.x (Simple)      →  P4.x (Group)      →  P5.x (Bridge)
   │                      │                    │
   ▼                      ▼                    ▼
Direct P2P             GROUP                 External
messages            destinations           protocol bridge
   │                      │                    │
   └──────────────────────┴────────┬──────────┘
                                  │
                            Bridge Interface
                            (abstract class)
```

#### Phase 1: Direct Peer-to-Peer

```
User A                        User B
   │                             │
   │  link.request("/chat", {   │
   │    "message": "hi",        │
   │    "from": "device_A"     │
   │  })                        │
   │ ──────────────────────────► │
   │                             │
   │  handler responds:         │
   │  { "ack": true }           │
   │ ◄───────────────────────── │
```

No persistence yet — messages only delivered to online peers.

#### Phase 2: GROUP Destinations for Circles

Create a RNS GROUP destination per "circle" (friends/family):

```
Circle "Friends" destination:
  personalcloudos.circles.<circle_id>

Members announce to this destination
Messages broadcast to all members
Offline members receive on next connect
```

#### Phase 3: Bridge Interface

```python
class MessageBridge(ABC):
    @abstractmethod
    async def send(self, message: ChatMessage) -> bool:
        pass
    
    @abstractmethod
    async def receive(self) -> AsyncIterator[ChatMessage]:
        pass
    
    @abstractmethod
    async def get_members(self) -> List[str]:
        pass
```

Implementations:
- `RNSChatBridge` — native PCOS messaging
- `MatrixBridge` — bridge to Matrix network
- `IRCBridge` — bridge to IRC

### CLI Access from Container

The PCOS container (Alpine Linux) should be able to access messaging:

**Option A: Unix Socket**
- PCOS exposes a Unix socket at `~/.local/run/pcos/messaging.sock`
- Container app connects via `connect("~/.local/run/pcos/messaging.sock")`
- Simple protocol over Unix socket (JSON messages)
- Socket uses file permissions (0600) for access control — only the owner user can connect
- More secure than network-based APIs since access is controlled by filesystem permissions

**Option B: Shared Volume**
- Mount shared volume at `/mnt/pcos`
- PCOS writes socket or named pipe there
- Container app reads/writes to communicate

**Option C: Import PCOS Modules**
- Mount PCOS source at `/mnt/pcos_src` inside container
- Container app can `import pcos` directly
- Works if container has same Python environment

All options keep the container isolated from direct RNS access while enabling messaging.

### Implementation Plan

```
P3.x
├── Add command handler /cmd/execute [DONE]
│   - Execute scripts, restart services
│   - Returns JSON result
├── Add status handler /status
│   - Share device inventory on request
│   - Can broadcast periodically
└── Basic peer-to-peer chat
    - /chat request handler
    - No persistence yet

P4.x
├── GROUP destinations for circles
│   - Create circle management
│   - Broadcast to group members
└── Message persistence
    - Store messages locally
    - Deliver to offline peers on connect

P5.x
├── Bridge interface (abstract)
├── Matrix bridge implementation
└── IRC bridge implementation
```

Each phase builds on the previous. The foundation (RNS request/response, GROUP destinations) is already available — we just need to wire it up.

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


---

## Self-Containment Architecture

*Added 2026-03-19*

### Vision

`git clone` + `python3 main.py --cli` = fully running node.
No internet. No package manager. No install steps. On any modern Linux.

### Dependency Audit

#### Pure Python (trivially vendorable)
| Package | Size | Used for | System deps |
|---------|------|----------|-------------|
| RNS (Reticulum) | 4.3MB | Core networking | None |
| pyserial | <1MB | Serial interfaces (RNS dep) | None |

#### Python with compiled extensions
| Package | Size | .so files | System deps needed |
|---------|------|-----------|-------------------|
| cryptography | 4.8MB | `_rust.abi3.so` | `libssl.so.3`, `libz`, `libzstd` |
| psutil | 904KB | `_psutil_linux.abi3.so` | `libc` only (universal) |
| Pillow | 3.4MB | 6 `.so` files | `libjpeg`, `libtiff`, `libwebp` + 12 more |

#### Notes on compiled extensions
- `cryptography` and `psutil` use `.abi3.so` (stable ABI) — work across Python 3.2+
- Pillow's `.so` files are **version-specific** (`cpython-313-x86_64`) — tied to Python 3.13
- Pillow is **optional** (system tray icon only) — can be replaced with pure-Python fallback
- `libssl`, `libz`, `libstdc++` are present on every modern Linux — safe assumption

#### External binary
| Binary | Size | System deps | Build tools needed |
|--------|------|-------------|-------------------|
| i2pd | ~15MB | None (static) | cmake, libboost-dev, libssl-dev |

### Directory Layout (target state)

```
project/
├── src/
│   ├── main.py              ← inserts vendor/ into sys.path at startup
│   ├── verify.py            ← startup self-check (Python ver, vendor, i2pd)
│   ├── vendor/              ← all Python dependencies (no pip needed)
│   │   ├── README.md
│   │   ├── RNS/
│   │   ├── serial/
│   │   ├── cryptography/
│   │   ├── psutil/
│   │   └── i2pd-src/        ← i2pd C++ source (git submodule)
│   ├── bin/
│   │   └── i2pd             ← static binary (committed, built once)
│   └── ... (app code)
├── BUILD.md                 ← how to rebuild everything from source
└── dist/                    ← PyInstaller output (gitignored)
    └── pcos/                ← complete distributable folder
```

### System Requirements (target state)

After self-containment work is complete, the only requirements are:

| Requirement | Why needed | Present on |
|-------------|-----------|------------|
| Python 3.10+ | Run the app | Ubuntu 22.04+, Debian 11+, Pop!_OS 22.04+, any modern Linux |
| `libssl.so.3` | cryptography extension | Any Linux with OpenSSL 3.x (2021+) |
| `libc` | Everything | Every Linux ever |
| `libz` | Compression | Every Linux ever |
| `libzstd` | Compression | Ubuntu 20.04+, Debian 10+ |

Nothing else. No apt, no pip, no docker, no internet.

### Platform Roadmap

| Platform | Status | Approach |
|----------|--------|----------|
| Linux x86_64 | Target (now) | Native Python + vendored deps |
| Linux aarch64 (Pi) | Soon | Same approach, ARM .so files needed |
| Windows | Later | PyInstaller builds .exe bundle |
| macOS | Later | PyInstaller builds .app bundle |
| Android | Later | BeeWare Briefcase → APK; TCP interface to desktop node |
| iOS | Future | BeeWare Briefcase → IPA |

### The Decentralization Stack

```
Application Layer    (pcos — this project)
       ↓
Identity Layer       (Reticulum cryptographic identity)
       ↓
Transport Layer      (AutoInterface=LAN, I2PInterface=internet, LoRa=radio)
       ↓
Physical Layer       (WiFi, Ethernet, radio, serial, anything)
```

No layer depends on any central authority. Each layer has multiple
implementations. Any node can be replaced or removed without affecting
others. The network heals around failures automatically.

### Internet Bridge Strategy

Nodes that choose to can bridge to the internet:
- Run a web server that serves a page describing the mesh
- Accept TCP connections from internet users as a Reticulum gateway
- Act as Reticulum transport nodes routing for mobile/lightweight clients
- These are **optional volunteer roles** — the mesh works without them
- The bridge is a recruitment tool: internet users join the mesh,
  reducing dependence on the internet one person at a time

### Compute Node Strategy

Always-on nodes with significant hardware (GPU, RAM) can offer compute:
- Desktop with RTX 4080 SUPER = GPU compute node on the mesh
- Any peer can request a GPU task, result returned over encrypted link
- No AWS, no cloud accounts — the mesh IS the cloud
- Node owners set their own terms for resource sharing

---

## Future Architecture: Two-Layer Model

### Vision (as of 2026-03-26)

A decentralized, encrypted operating system that runs as a second layer over any host OS, with blockchain for state synchronization.

### Layer 1: PCOS Host Layer

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Host OS (any Linux distro, Alpine, Debian, etc)│
│  - PCOS App runs as a background service                   │
│  - Establishes RNS mesh networking                          │
│  - Manages identities (user, circles)                       │
│  - Hardware resource sharing (GPU, storage)                │
│  - Provides encrypted partition to Layer 2                 │
└─────────────────────────────────────────────────────────────┘
```

**Current state:** ✓ Implemented in v1.3.x
- RNS networking works
- Identity management works  
- File sync works

### Layer 2: Guest OS (Encrypted Container)

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 2: Guest OS (Alpine Linux + busybox + musl)         │
│  - Encrypted, invisible to host OS                         │
│  - Sees hardware directly (GPU passthrough)                 │
│  - Runs like any native app to user                         │
│  - State synced via blockchain + RNS                       │
│  - Shared across all user's devices as one virtual OS       │
└─────────────────────────────────────────────────────────────┘
```

**Current state:** ▼ Not implemented
- Alpine rootfs bundled in repo (✓)
- Shell access works (✓)
- Not encrypted (TODO)
- Not invisible to host (TODO)
- GPU passthrough (TODO)

### State Synchronization Options

The goal is to keep all devices in sync with the same OS state. Blockchain is ONE way to do this, but there are others:

#### Option 1: Direct Sync (Current)
- Devices sync files/state directly via RNS
- Simple, works for file sync already
- May not handle complex state (running processes, etc)

#### Option 2: CRDT (Conflict-free Replicated Data Types)
- Data structures that auto-merge across devices
- Used by real-time apps (Google Docs, etc)
- No blockchain needed

#### Option 3: IPFS + Local State
- IPFS for content-addressed data
- Local state database synced as files
- Proven approach

#### Option 4: Light Blockchain
- Minimal chain for state commit history
- Not for currency, just for ordering
- IOTA, Temporal, or custom

#### Option 5: Centralized (Not Preferred)
- One device as "master" - goes against decentralization goal

### Decision: EXPLORE, NOT DECIDED

We will try the simplest approach first (direct sync) and only add complexity if needed.

### The Real Challenge

The goal isn't just "invisible to host OS" - that's encryption (solved problem).

The REAL challenge is:

1. **State Persistence**
   - OS state must survive device restarts
   - Must live in RNS mesh, not on any single device
   - When you start PCOS with 1 device, it loads your OS from the mesh

2. **Zero-Config Mirroring** 
   - Connect second device = it automatically shows the same OS state
   - Like plugging in a second monitor
   - No setup, no pairing, just works

3. Device-Specific Optimization
   - Same OS state, but adapts to screen size, GPU, etc.
   - Phone vs Desktop vs Tablet - different views of same state

4. Why UI Matters
   - CLI/Terminal = SAME everywhere = easiest to mirror
   - GUI = needs adaptation per device
   - Hybrid approach: CLI-base + optional GUI layer
   - "Universal terminal" as the common denominator

### Implications for Design

- Terminal-first architecture (everything accessible via CLI)
- State stored in mesh (RNS), not local filesystem  
- Guest OS boots FROM the mesh, not from local disk
- Second device connects to mesh, gets current state automatically

### Options Analysis

Given the requirements (state in mesh, boot from mesh, auto-mirror, CLI-first), here are the options:

---

#### 1. How to Store State in Mesh?

| Option | How It Works | Pros | Cons |
|--------|--------------|------|------|
| **A. RNS File Sync** | SQLite + RNS transfer | Simple, works now | No ordering guarantee |
| **B. IPFS** | Content-addressed storage | Proven, deduplication | Extra dependency |
| **C. Custom RNS State** | Store state in RNS packets | Built into our network | Limited size |
| **D. State Provider** | One device holds state, others query | Simple | Not fully decentralized |

**Recommendation:** Start with A (current), move to D if needed

---

#### 2. How to Boot from Mesh with 1 Device?

| Option | How It Works | Pros | Cons |
|--------|--------------|------|------|
| **A. Last-Writer-Wins** | Most recent state wins | Simple | Can lose updates |
| **B. Primary Device** | One device is "source of truth" | Clear ordering | Not decentralized |
| **C. Vector Clocks** | Track causality, merge | Proper sync | Complex |
| **D. Raft/Paxos** | Consensus algorithm | Strong consistency | Heavy for mesh |

**Recommendation:** Start with A, add C if conflicts become problem

---

#### 3. How to Auto-Mirror (Second Device)?

| Option | How It Works | Pros | Cons |
|--------|--------------|------|------|
| **A. RNS Broadcast** | Announce + state push | Built into network | Not real-time |
| **B. Persistent Links** | All devices maintain connections | Real-time sync | Complexity |
| **C. Session Server** | One device runs "display server" | Simple mirroring | Device dependent |
| **D. State Subscription** | Devices subscribe to state changes | Clean separation | Need state server |

**Recommendation:** Start with C (one device is display server), evolve to D

---

#### 4. Guest OS Options (Layer 2)

| Option | How It Works | Pros | Cons |
|--------|--------------|------|------|
| **A. chroot + PATH** | Current approach | No root needed | Not isolated |
| **B. systemd-nspawn** | Container with namespaces | Better isolation | Needs systemd |
| **C. Firecracker** | MicroVM (AWS VMC) | Strong isolation | Heavy |
| **D. AppImage** | Self-contained executable | Portable | Not a true VM |

**Recommendation:** Start with A (works now), move to B when possible, D for final product

---

#### 5. UI Options (for device adaptation)

| Option | How It Works | Pros | Cons |
|--------|--------------|------|------|
| **A. CLI/Terminal** | Text-based, always same | Easy mirroring | Not graphical |
| **B. Terminal GUI** | ncurses, text UIs | Better UX, same everywhere | Limited |
| **C. Web Interface** | Browser connects to socket | Cross-platform | Not native |
| **D. Progressive Web App** | PWA that adapts | Native-like, flexible | More work |

**Recommendation:** A+B first (CLI-first), add C for convenience, D for final

---

### Summary: Recommended Path

1. **State:** RNS file sync + simple last-writer-wins
2. **Boot:** One device holds state, others fetch
3. **Mirror:** Session-based (one device shows, others connect)
4. **Guest:** chroot now, AppImage for product
5. **UI:** Terminal-first, web for convenience

Complex solutions (blockchain, Raft, IPFS) only if simpler ones don't work.

### Phased Roadmap

| Phase | Focus | Status | Notes |
|-------|-------|--------|-------|
| 1 | Foundation (RNS, sync, identities) | ✓ Done | Networking, file sync work |
| 2 | State Persistence in Mesh | TODO | OS state lives in RNS, not local |
| 3 | Single-Device Boot from Mesh | TODO | Start PCOS = load state from mesh |
| 4 | Auto-Mirror on Second Device | TODO | Zero-config display mirroring |
| 5 | Encrypted Container | TODO | Invisible to host (final goal) |
| 6 | GPU/Hardware Passthrough | TODO | Guest sees real hardware |
| 7 | Device Optimization | TODO | Same state, adapted views |

Note: We will NOT add blockchain unless simpler approaches (direct sync, CRDT) prove insufficient.

---

*Last updated: 2026-03-26*
