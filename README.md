# Personal Cloud OS

A self-contained Linux environment with ZeroTrust networking that runs in the background, automatically discovers peers on your network, syncs files, and provides your personal Linux environment.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         THE APP                                   │
│                                                                  │
│   ┌───────────────────────────────────────────────────────────┐ │
│   │  RETICULUM NETWORK LAYER (Background)                    │ │
│   │  • Embedded RNS library (no rnsd daemon needed)           │ │
│   │  • Auto-starts rnsd if not running                      │ │
│   │  • Identity-based peer discovery                         │ │
│   │  • Encrypted P2P links                                  │ │
│   └───────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│   ┌───────────────────────────────────────────────────────────┐ │
│   │  PEER DISCOVERY SERVICE (Background)                     │ │
│   │  • Uses rnstatus to query Reticulum paths               │ │
│   │  • Discovers peers on local network                      │ │
│   │  • Auto-discovers devices with same user identity        │ │
│   └───────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│   ┌───────────────────────────────────────────────────────────┐ │
│   │  SYNC ENGINE (Background)                                 │ │
│   │  • Syncs files with discovered peers                     │ │
│   │  • Handles conflicts                                     │ │
│   │  • Delta sync for efficiency                             │ │
│   └───────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│   ┌───────────────────────────────────────────────────────────┐ │
│   │  CONTAINER WITH YOUR LINUX OS (Background)                │ │
│   │  • Alpine/Debian environment                             │ │
│   │  • Your files, configs, terminal                         │ │
│   │  • All your tools (git, python, vim, etc.)              │ │
│   └───────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│   ┌───────────────────────────────────────────────────────────┐ │
│   │  APP LAUNCHER / DISPLAY                                  │ │
│   │  • Tkinter UI                                            │ │
│   │  • Shows peer status, sync status, container status      │ │
│   └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Features

### 🔐 ZeroTrust Networking
- Uses **Reticulum** for encrypted peer-to-peer communication
- No central server - fully decentralized
- Identity-based authentication (same identity = trusted peer)

### 👥 Peer Discovery
- Automatic discovery of devices on local network
- Uses Reticulum's AutoInterface for local discovery
- Polls `rnstatus` for real-time peer information

### 📁 File Sync
- Bidirectional file synchronization
- Conflict detection and resolution
- Encrypted transfers via Reticulum links

### 🐧 Linux Container
- Runs Alpine Linux in a Docker container
- Your personal environment available anywhere
- Terminal access via UI

### 🖥️ Desktop UI
- Tkinter-based launcher
- Shows peer status, sync status, container status
- Open apps: Terminal, Files, Calendar, Editor, Settings

## Installation

```bash
# Clone the repo
git clone https://github.com/jonatse/personal-cloud-os.git
cd personal-cloud-os

# Install dependencies
pip install -r requirements.txt

# Install Reticulum (if not already installed)
pip install rns
```

## Running

```bash
cd src
python3 main.py
```

This will:
1. Start Reticulum networking (auto-starts rnsd if needed)
2. Initialize peer discovery
3. Start sync engine
4. Launch the Tkinter UI

## Configuration

Edit `src/core/config.py` or create `config.yaml`:

```yaml
app:
  name: "MyCloudOS"
  debug: false

reticulum:
  announce_interval: 30
  identity_path: "~/.reticulum/storage/identities/pcos_device"

sync:
  sync_interval: 60
  conflict_resolution: "newest"
  sync_dir: "~/Sync"

container:
  auto_start: true
  image: "alpine:latest"
  name: "personal-cloud-os"
```

## Peer Discovery

### How it works

1. Each device generates a unique **device identity** (`pcos_device`)
2. Reticulum's AutoInterface discovers peers on the local network
3. The discovery service polls `rnstatus` every 5 seconds
4. Found peers are stored with their Reticulum hash

### Testing Discovery

```python
# Quick test
cd src
python3 -c "
import asyncio
import sys
sys.path.insert(0, '.')
from core.config import Config
from core.events import event_bus
from services.reticulum_peer import ReticulumPeerService
from services.discovery import PeerDiscoveryService

async def test():
    config = Config()
    reticulum = ReticulumPeerService(config, event_bus)
    await reticulum.start()
    
    discovery = PeerDiscoveryService(config, event_bus)
    discovery.set_reticulum_service(reticulum)
    await discovery.start()
    
    for i in range(20):
        await asyncio.sleep(3)
        peers = discovery.get_peers()
        print(f'Found {len(peers)} peers')
        for p in peers:
            print(f'  - {p.name}: {p.reticulum_hash[:20]}...')
    
    await discovery.stop()
    await reticulum.stop()

asyncio.run(test())
"
```

## File Structure

```
personal-cloud-os/
├── SPEC.md                 # Architecture specification
├── requirements.txt       # Python dependencies
├── README.md              # This file
└── src/
    ├── main.py            # Entry point
    ├── core/
    │   ├── config.py      # Configuration management
    │   ├── events.py      # Event system
    │   └── logger.py      # Logging setup
    ├── services/
    │   ├── reticulum_peer.py   # Reticulum networking
    │   ├── discovery.py        # Peer discovery
    │   ├── peer_link.py       # P2P links
    │   └── sync.py            # File sync engine
    ├── container/
    │   └── manager.py         # Docker container management
    └── ui/
        ├── launcher.py        # Tkinter UI
        └── components.py      # UI components
```

## Dependencies

- **Python 3.10+**
- **rns** - Reticulum networking stack
- **aiohttp** - Async HTTP (future use)
- **PyYAML** - Configuration
- **colorlog** - Colored logging

## Network Interfaces

The app supports multiple network interfaces:

1. **AutoInterface** (default) - Local network discovery via UDP
2. **TCP Interface** - For wider networks (configure in `~/.reticulum/config`)
3. **Serial/LoRa** - For radio-based networks (future)

## Troubleshooting

### No peers discovered
1. Ensure both devices are on the same network
2. Check that rnsd is running: `rnstatus`
3. Check path table: `rnpath -t`

### Start rnsd manually
```bash
~/.local/bin/rnsd -s
```

### Check network interfaces
```bash
rnstatus -v
```

## Future Enhancements

- [ ] File transfer via Reticulum links
- [ ] TCP interface for cross-network communication
- [ ] Audio-based peer discovery
- [ ] RF-based peer discovery
- [ ] End-to-end encryption for all traffic
- [ ] Mobile support (iOS/Android)

## License

MIT License - See LICENSE file
