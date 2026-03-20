# Personal Cloud OS

A self-contained, ZeroTrust peer-to-peer networking layer for personal devices.
Devices find each other automatically over any local network using
[Reticulum](https://reticulum.network/) — no central server, no port-forwarding,
no cloud accounts required.

---

## What Works Right Now

| Feature | Status | Notes |
|---------|--------|-------|
| Reticulum ZeroTrust networking | ✅ Working | Identity-based, encrypted by default |
| LAN peer discovery | ✅ Working | Devices find each other automatically |
| Peer announcements | ✅ Working | Every device announces every 30s |
| Persistent device identity | ✅ Working | Survives restarts |
| Device inventory | ✅ Working | Tracks known devices + hardware info |
| Curses CLI (split-screen) | ✅ Working | Live header, scrolling output, persistent prompt |
| CLI command: `peers` | ✅ Working | Lists discovered peers with ID |
| CLI command: `network` | ✅ Working | Shows identity hash, destination, announce interval |
| CLI command: `device` | ✅ Working | Shows local device info |
| CLI command: `status` | ✅ Working | Reticulum, peers, sync, container at a glance |
| CLI command: `sync` | ✅ Working | Shows sync state (engine runs, no transfers yet) |
| CLI command: `container` | ✅ Working | Shows container state |
| File sync engine (structure) | 🔧 Partial | Scans files, peer protocol defined, transfers broken |
| Encrypted P2P links | 🔧 Partial | `create_link()` exists, destination type bug |
| System tray icon | 🔧 Partial | Works if pystray + Pillow installed |
| Container runtime | ❌ Requires Docker | P0 priority: replace with self-contained runtime |
| Resource sharing | ❌ Not started | Phase 3 goal |
| Session persistence | ❌ Not started | Phase 3 goal |

---

## Quick Start

### Requirements

```
Python 3.10+
pip install -r requirements.txt
```

**Key dependencies:**
- `rns` — Reticulum networking stack
- `psutil` — hardware/network detection
- `pystray` + `Pillow` — optional system tray icon

### Run

```bash
cd src/

# Interactive CLI (recommended)
python3 main.py --cli

# Background service only (no CLI)
python3 main.py

# Background + system tray icon
python3 main.py --tray
```

### Run on second device

Repeat the same steps on any other device on the same LAN.
They will find each other automatically within ~30 seconds.

---

## CLI Reference

The CLI uses a split-screen curses layout:

```
┌─────────────────────────────────────────────────────────────┐
│  Personal Cloud OS  │  hostname  │  Online                  │  ← live header
│  Identity : abcd1234...   Dest : ef567890...                │
│  Peers    : ● 1 connected  — pop-osmark                     │  ← green = connected
│  Sync     : idle           Container : Stopped              │
│  ──────────────────────────────────────────────────────────  │
│  help · peers · sync · network · device · exit · quit       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  (command output scrolls here)                             │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  pcos ❯ _                                                   │  ← persistent prompt
└─────────────────────────────────────────────────────────────┘
```

The header refreshes automatically every 5 seconds.
Use ↑/↓ arrow keys to navigate command history.

### Commands

| Command | Description | Example |
|---------|-------------|---------|
| `help` | List all available commands | `help` |
| `status` | Full system status snapshot | `status` |
| `peers` | List all discovered peers with IDs | `peers` |
| `network` | Show Reticulum identity, destination hash, announce settings | `network` |
| `device` | Show local device info (hostname, platform, identity) | `device` |
| `sync` | Show sync engine state, file counts, sync directory | `sync` |
| `container` | Show container running state | `container` |
| `start <service>` | Start a service *(stub — not yet implemented)* | `start sync` |
| `stop <service>` | Stop a service *(stub — not yet implemented)* | `stop sync` |
| `restart <service>` | Restart a service *(stub — not yet implemented)* | `restart peers` |
| `clear` | Clear the output pane | `clear` |
| `exit` | Close the CLI, keep app running in background | `exit` |
| `quit` | Close the CLI *(background service keeps running — same as exit for now)* | `quit` |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Personal Cloud OS                       │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │             ReticulumPeerService                     │  │
│  │                                                      │  │
│  │  • Initialises RNS stack (no external rnsd needed)   │  │
│  │  • Loads / creates persistent device identity        │  │
│  │  • Registers announce handler                        │  │
│  │  • Background thread: announces presence every 30s   │  │
│  │  • Receives announces → stores peers in _peers dict  │  │
│  │  • Publishes peer.discovered / peer.updated events   │  │
│  │  • create_link(peer_id) → RNS.Link (WIP)             │  │
│  └──────────────────────────┬───────────────────────────┘  │
│                             │ events                        │
│           ┌─────────────────┼──────────────────┐           │
│           ▼                 ▼                  ▼           │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────┐  │
│  │ PeerLinkSvc  │  │   SyncEngine    │  │  EventBus    │  │
│  │              │  │                 │  │              │  │
│  │ Manages RNS  │  │ Scans ~/Sync    │  │ pub/sub for  │  │
│  │ Link objects │  │ File manifest   │  │ all services │  │
│  │ (WIP)        │  │ JSON protocol   │  │              │  │
│  └──────────────┘  │ (partial)       │  └──────────────┘  │
│                    └─────────────────┘                     │
│                                                             │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────┐  │
│  │ DeviceManager│  │ContainerManager │  │  CLIInterface│  │
│  │              │  │                 │  │              │  │
│  │ Fingerprints │  │ Docker (P0:     │  │ Curses UI    │  │
│  │ device by    │  │ replace with    │  │ live header  │  │
│  │ hostname+MAC │  │ self-contained) │  │ + scroll pane│  │
│  │ inventory    │  │                 │  │ + prompt     │  │
│  └──────────────┘  └─────────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### Key design decisions

**Single networking layer** — Reticulum handles everything: identity, discovery,
encryption, transport. There is no separate discovery service (it was removed —
see `src/shelf/discovery.py` for the archived code and explanation).

**ZeroTrust by default** — every device has a cryptographic identity
(`~/.reticulum/storage/identities/pcos_<mac>`). Peers are identified by their
identity hash, not by IP address. Communication is encrypted at the Reticulum
layer without any additional configuration.

**Offline-first** — the app starts and runs fully without internet. LAN peers
are discovered via Reticulum's AutoInterface (UDP multicast). Internet-routable
discovery (via Reticulum TCP interfaces or Tailscale) is a future addition.

---

## File Structure

```
project/
├── README.md               ← this file
├── SPEC.md                 ← design specification
├── GOALS.md                ← priority tracking / known issues
├── requirements.txt
├── start.sh                ← convenience launcher
├── cli.sh                  ← opens CLI in new terminal
└── src/
    ├── main.py             ← entry point, service orchestrator
    ├── core/
    │   ├── config.py       ← config load/save (~/.config/pcos/config.json)
    │   ├── events.py       ← in-process pub/sub event bus
    │   ├── logger.py       ← logging setup
    │   ├── version.py      ← version string
    │   └── device_manager.py ← device fingerprinting + inventory
    ├── services/
    │   ├── reticulum_peer.py  ← ★ core: ZeroTrust networking + peer discovery
    │   ├── peer_link.py       ← encrypted P2P link manager (WIP)
    │   └── sync.py            ← file sync engine (partial)
    ├── container/
    │   └── manager.py      ← container runtime (currently requires Docker)
    ├── cli/
    │   ├── interface.py    ← curses split-screen CLI
    │   └── commands.py     ← command implementations
    ├── tray/
    │   └── system_tray.py  ← optional system tray icon
    ├── ui/
    │   ├── launcher.py     ← Tkinter GUI launcher (not wired to main.py yet)
    │   └── components.py   ← reusable Tk widgets (not yet used by launcher)
    └── shelf/
        ├── __init__.py     ← shelf index
        └── discovery.py    ← archived: old two-layer discovery service
```

---

## Device Identity

Each device gets a stable cryptographic identity on first run, stored at:

```
~/.reticulum/storage/identities/pcos_<last6ofMAC>
```

The identity is derived from **hostname + MAC address** → SHA-256 → `device_id`.
This means:
- The same device always gets the same identity
- If you re-install the OS, a new identity is created (new MAC possible)
- Identities are **not** shared between devices — each is unique

The **device inventory** lives at `src/core/device_inventory.json` and tracks
hardware, network, and SSH info for each known device.

> ⚠️ **Do not commit plaintext credentials to the inventory file.**
> The `.gitignore` excludes `device_inventory.json` for this reason.

---

## Configuration

Config file: `~/.config/pcos/config.json` (created automatically on first run)

```json
{
  "app": {
    "debug": false,
    "log_level": "INFO"
  },
  "reticulum": {
    "identity_path": "~/.reticulum/storage/identities/pcos",
    "announce_interval": 30
  },
  "sync": {
    "sync_dir": "~/Sync",
    "sync_interval": 60,
    "conflict_resolution": "newest"
  },
  "container": {
    "auto_start": true,
    "image": "alpine:latest",
    "name": "pcos-container"
  }
}
```

---

## Known Issues / Bugs

See `GOALS.md` for the full priority list. Critical issues:

1. **`ReticulumPeerService.stop()` never stops** — inverted guard (`if self._running: return` should be `if not self._running: return`)
2. **`create_link()` will fail at runtime** — `ReticulumPeer.destination` stores an `RNS.Identity`, but `RNS.Link()` requires an `RNS.Destination`
3. **Container requires Docker** — P0 priority to replace with a self-contained runtime
4. **`cmd_start/stop/restart` are stubs** — they print a message but do nothing
5. **`cmd_quit` does not stop the background service** — it only closes the CLI

---

## Shelved Code

`src/shelf/` contains code that was removed from active use but kept for reference:

| File | What it was | Why removed |
|------|------------|-------------|
| `discovery.py` | Two-layer discovery service wrapping Reticulum | Race condition between layers caused peer count to always show 0; merged into ReticulumPeerService directly |

