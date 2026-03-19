# Personal Cloud OS - Design Requirements

## Document Purpose

**SPEC.md** - Design specification (what we ARE building)
**GOALS.md** - Priority tracking (what we are WORKING ON now)

## Core Principles

1. **Zero Configuration** - Works automatically once installed
2. **Self-Contained** - All dependencies bundled, no external downloads needed
3. **Background First** - Runs as a background service, not a GUI app
4. **CLI-First Interface** - All management via terminal
5. **Cross-Platform** - Works identically on desktop, laptop, server
6. **Network-Agnostic** - Works over local WiFi, TCP, or future transport layers

---

## Functional Requirements

### FR1: Background Service
- **FR1.1**: App starts automatically on system boot (optional)
- **FR1.2**: Runs in background with no visible window by default
- **FR1.3**: Shows system tray notification when running
- **FR1.4**: Clicking notification opens CLI management interface in default terminal
- **FR1.5**: Can be started/stopped via CLI commands

### FR2: Peer Discovery
- **FR2.1**: Automatically discovers other devices running Personal Cloud OS
- **FR2.2**: Uses Reticulum for ZeroTrust encrypted networking
- **FR2.3**: Same user identity = trusted peers for file sharing
- **FR2.4**: Unique device identity for each device
- **FR2.5**: Displays peer status (online/offline, connection quality)

### FR3: Device Inventory
- **FR3.1**: Automatic hardware detection on startup
  - CPU (cores, speed, architecture)
  - RAM (total, available)
  - GPU (graphics cards, capabilities)
  - Audio devices (input/output)
  - Video devices (cameras, displays)
- **FR3.2**: Network interface discovery
  - IP addresses (IPv4, IPv6)
  - Network names/SSIDs
  - Connection types (WiFi, ethernet, etc.)
- **FR3.3**: Device credential storage
  - Username for this device
  - SSH credentials (password/key)
  - Used for authentication between devices
- **FR3.4**: Device registry (shared across user's devices)
  - List of all devices owned by user
  - Each device's hardware capabilities
  - Network information
  - App installation path on each device
- **FR3.5**: App location tracking
  - Path to app installation directory on this device
  - Used for remote management and locating app files
  - Can be queried via CLI for troubleshooting
- **FR3.6**: Device inventory file
  - Stored at `src/core/device_inventory.json`
  - Contains device registry with all user devices
  - Each device entry includes: name, hostname, is_local flag, SSH credentials, project_path, last_updated
  - SSH credentials include: user, host, port, password
  - Used for device discovery and remote access

### FR4: File Sync
- **FR4.1**: Automatically syncs files between discovered peers
- **FR4.2**: End-to-end encrypted transfers
- **FR4.3**: Conflict detection and resolution
- **FR4.4**: Configurable sync directories

### FR5: Resource Sharing
- **FR5.1**: Share CPU resources with virtual environment
- **FR5.2**: Share RAM with virtual environment  
- **FR5.3**: Share GPU compute with virtual environment
- **FR5.4**: Share audio devices (input/output)
- **FR5.5**: Share video devices (cameras, displays)
- **FR5.6**: Network bridging to virtual environment
- **FR5.7**: GPU passthrough for graphics acceleration

### FR6: Session State Persistence
- **FR6.1**: Terminal session state preservation
  - Command history preserved across devices
  - Working directory preserved
  - Environment variables preserved
- **FR6.2**: Application state preservation
  - GUI apps stay open when switching devices
  - App state (windows, documents) persisted
- **FR6.3**: Seamless resume on different device
  - User continues work exactly where left off
  - No manual reconnection needed

### FR7: Container Environment
- **FR7.1**: Runs Alpine Linux container in background
- **FR7.2**: Accessible via SSH from CLI interface
- **FR7.3**: Persistent storage for user files
- **FR7.4**: SSH daemon running in container

### FR8: CLI Management Interface
- **FR8.1**: Interactive CLI with menu-driven interface
- **FR8.2**: Commands: status, peers, sync, device, network, help, exit
- **FR8.3**: Colored output for readability
- **FR8.4**: Tab completion for commands
- **FR8.5**: Real-time status updates

### FR9: Self-Contained Packaging
- **FR9.1**: Single executable or self-contained directory
- **FR9.2**: Includes all Python dependencies
- **FR9.3**: Includes Reticulum binaries if needed
- **FR9.4**: Works without internet after initial install

---

## User Interface Specification

### System Tray
- **Icon**: Cloud icon indicating Personal Cloud OS
- **Tooltip**: Shows peer count and sync status
- **Left-click**: Opens CLI management interface
- **Right-click**: Context menu (Status, Start/Stop, Quit)

### CLI Interface
```
┌─────────────────────────────────────────────────┐
│  Personal Cloud OS v1.0                         │
├─────────────────────────────────────────────────┤
│  Status: Running    Peers: 1    Sync: Idle      │
├─────────────────────────────────────────────────┤
│  > status                                      │
│                                                │
│  Reticulum: Online                             │
│  Identity: abcd1234...                         │
│  Peers:                                        │
│    - laptop (1 hop, encrypted)                 │
│  Sync:                                         │
│    - /home/user/Cloud: idle                   │
│  Container: Running (SSH: localhost:2222)      │
│                                                │
│  Type 'help' for available commands            │
└─────────────────────────────────────────────────┘
```

---

## Technical Architecture

```
┌─────────────────────────────────────────────────┐
│              Host Operating System              │
│    (Linux, started on boot via systemd/launchd) │
└──────────────────────┬──────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│            Personal Cloud OS Service            │
│                                                  │
│  ┌────────────────────────────────────────────┐ │
│  │  Reticulum Network Layer                   │ │
│  │  - ZeroTrust encrypted networking          │ │
│  │  - Peer discovery                         │ │
│  │  - File transfer                           │ │
│  └────────────────────────────────────────────┘ │
│                                                  │
│  ┌──────────────┐  ┌──────────────────────────┐ │
│  │   Service   │  │    Container Manager     │ │
│  │   Manager   │  │  ┌────────────────────┐  │ │
│  │  - Start    │  │  │  Alpine Linux      │  │ │
│  │  - Stop     │  │  │  - SSH Daemon      │  │ │
│  │  - Status   │  │  │  - User Files      │  │ │
│  └──────────────┘  │  │  - Tools           │  │ │
│                     │  └────────────────────┘  │ │
│                     └──────────────────────────┘ │
└──────────────────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────┐
│           CLI Management Interface              │
│    (Opens in terminal when tray icon clicked)   │
└──────────────────────────────────────────────────┘
```

---

## Module Structure

```
src/
├── main.py                    # Entry point, service startup
├── cli/
│   ├── __init__.py
│   ├── interface.py          # Interactive CLI shell
│   └── commands.py           # CLI commands
├── core/
│   ├── __init__.py
│   ├── config.py             # Configuration
│   ├── events.py             # Event bus
│   └── logger.py             # Logging
├── device/
│   ├── __init__.py
│   ├── inventory.py          # Hardware detection
│   ├── registry.py           # Device registry
│   └── resources.py         # Resource allocation
├── services/
│   ├── __init__.py
│   ├── reticulum_peer.py     # Reticulum networking
│   ├── discovery.py          # Peer discovery
│   ├── peer_link.py          # P2P links
│   └── sync.py               # File sync
├── container/
│   ├── __init__.py
│   └── manager.py            # Docker container
├── tray/
│   ├── __init__.py
│   └── system_tray.py       # System tray icon
└── install/
    ├── setup.py              # Installation script
    └── requirements.txt      # Python dependencies
```

---

## Acceptance Criteria

### AC1: Installation
- [ ] Can be installed with single command or script
- [ ] No external dependencies required at runtime
- [ ] Works on fresh Linux install

### AC2: Background Operation
- [ ] App runs in background after launch
- [ ] System tray icon appears
- [ ] Services start automatically
- [ ] Works over SSH (no display required)

### AC3: Peer Discovery
- [ ] Discovers other devices on same network
- [ ] Shows peer status in CLI
- [ ] Connection is encrypted

### AC4: File Sync
- [ ] Syncs files between devices
- [ ] Shows sync status
- [ ] Handles conflicts gracefully

### AC5: CLI Interface
- [ ] Opens in terminal from tray click
- [ ] Shows real-time status
- [ ] All commands work as documented

### AC6: Consistency
- [ ] Works identically on laptop and desktop
- [ ] Same commands, same behavior
- [ ] No device-specific configuration needed
