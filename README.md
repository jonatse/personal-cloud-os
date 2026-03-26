# Personal Cloud OS

A self-contained, offline-first personal cloud that syncs files across your devices using [Reticulum](https://reticulum.network/) — encrypted, peer-to-peer, no central server, no cloud accounts.

---

## What Works Right Now

| Feature | Status |
|---------|--------|
| Reticulum networking (no rnsd needed) | Working |
| LAN peer discovery | Working |
| File sync between devices | Working |
| Persistent device identity | Working |
| Curses CLI (split-screen) | Working |
| Identity-based access control | Working |
| Remote command execution (via Unix socket) | Working |
| Socket API for container control | Working |

---

## Architecture: Network Layer vs Application Layer

```
NETWORK LAYER (Reticulum):
  • Identity = cryptographic keypair, used as address
  • Announce = broadcasts identity for discovery
  • No ports needed = address is hash, not IP:port
  • Encrypted by default
  • Routes for ALL devices (mesh works for everyone)

APPLICATION LAYER (PCOS):
  • Same identity = full access (your devices)
  • Circle identity = limited access (friends)
  • Unknown = minimal/no access
```

---

## Access Levels

### Your Devices (Personal Identity)
- Full file sync
- GPU compute sharing
- All PCOS services
- Access to /home

### Friends (Circle Identity)
- Shared folders sync
- Chat messages
- One-off file transfers
- **No** access to /home
- **No** GPU compute

### Unknown
- Cannot access your files
- Can route through your mesh (helps the network)

---

## Socket API (Container Control)

PCOS exposes a Unix socket for control and diagnostics:

| Path | `~/.local/run/pcos/messaging.sock` |
|------|-------------------------------------|
| Protocol | JSON over Unix socket |
| Permissions | 0600 (owner only) |

### Available Commands

```bash
# Get peer list
echo '{"cmd": "peers"}' | nc -U ~/.local/run/pcos/messaging.sock

# Execute remote command
echo '{"cmd": "execute", "peer": "pop-osmark", "command": "echo hello"}' | nc -U ~/.local/run/pcos/messaging.sock

# Get status
echo '{"cmd": "status"}' | nc -U ~/.local/run/pcos/messaging.sock
```

This allows the container (Alpine Linux) to control PCOS and execute commands on remote peers.

---

## Quick Start

### Requirements
```
Python 3.10+
```

### Run
```bash
cd src/

# Interactive CLI (recommended)
python3 main.py --cli

# Background service only
python3 main.py
```

### Add a new device
```bash
# On new device
pcos identity import
# Paste identity string from primary device OR scan QR

# Now shares YOUR identity = automatic trust = full sync
```

---

## CLI Commands

| Command | Description |
|---------|-------------|
| help | List commands |
| status | Full system status |
| peers | List discovered peers |
| network | Show Reticulum identity |
| device | Show local device info |
| sync | Show sync state |
| identity | Manage identities (create, show, import, export) |
| circle | Manage circles (create, add, remove) |

---

## Identity System

### Personal Identity (your devices)
Create once, copy to all your devices:
```bash
pcos identity create
pcos identity show-qr  # show for other devices to scan
```

### Circle Identity (friends/family)
Create a circle, add friends:
```bash
pcos circle create family
pcos circle show-qr family  # friend scans this
pcos circle import        # friend imports
```

---

## Running on Multiple Devices

1. Create identity on primary device: pcos identity create
2. Copy identity to other devices (QR code or string)
3. Devices automatically discover each other
4. File sync begins automatically

---

## File Structure

```
project/
├── README.md              ← this file
├── SPEC.md                ← design specification
├── GOALS.md               ← priority tracking
├── requirements.txt
├── src/
│   ├── main.py            ← entry point
│   ├── core/
│   │   ├── config.py      ← config management
│   │   ├── events.py      ← pub/sub event bus
│   │   ├── logger.py      ← logging
│   │   ├── version.py     ← version
│   │   └── device_manager.py ← device fingerprinting
│   ├── services/
│   │   ├── reticulum_peer.py  ← networking + discovery
│   │   ├── sync.py            ← file sync
│   │   └── i2p_manager.py     ← I2P for internet
│   ├── cli/
│   │   ├── interface.py   ← curses UI
│   │   └── commands.py    ← CLI commands
│   ├── transport/
│   │   ├── detector.py    ← transport classification
│   │   ├── bandwidth.py   ← bandwidth management
│   │   └── wireguard.py   ← future: WireGuard
│   └── vendor/
│       └── RNS/           ← vendored Reticulum
├── shelf/                 ← archived code
└── scripts/
    ├── deploy.sh          ← deploy to devices
    ├── device_kill.sh
    ├── device_pull.sh
    └── device_restart.sh
```

---

## Design Principles

1. ZeroTrust — Every device has cryptographic identity. Trust comes from identity, not IP.

2. Offline-first — Works without internet. LAN via UDP multicast (Reticulum AutoInterface). Internet via I2P (future).

3. Self-contained — git clone + python3 main.py = working. No pip install, no Docker required (container feature is P0).

4. Identity-based — Your identity = trust. Same identity = full access. Circle identity = limited access. Unknown = nothing.

---

## Future Phases

- I2P integration — Internet connectivity without port forwarding
- QR code onboarding — Scan QR to add device
- Shared Linux environment — Your devices as a decentralized compute cluster
- GPU passthrough — Use desktop GPU from laptop

---

## Known Issues

See GOALS.md for full priority list. Current focus: Priority 1.5 (Identity & Trust System)

---

## License

This project is for building personal, decentralized infrastructure. See Reticulum's license for the networking stack.
