# Personal Cloud OS - Architecture Specification

## Overview
A personal cloud OS that runs in the background like a service, discovers peers automatically, syncs everything, and provides your full Linux environment.

## Core Components

### 1. Peer Discovery Service (Background)
- **Purpose**: Finds other devices on the network
- **Runs**: Always, even when app is "closed"
- **Discovery Methods**:
  - mDNS/Bonjour for local network discovery
  - Peer ID broadcasting
  - Audio/RF discovery (future)
- **Output**: List of available peers with connection info

### 2. Sync Engine (Background)
- **Purpose**: Syncs files with discovered peers
- **Runs**: Always
- **Features**:
  - Bidirectional file synchronization
  - Conflict detection and resolution
  - Delta sync for efficiency
  - Encrypted transfer

### 3. Container with Linux OS (Background)
- **Purpose**: Provides your personal Linux environment
- **Runs**: Always - like a background service
- **Contents**:
  - Alpine/Debian base
  - Your files and configs
  - Terminal access
  - Your tools (git, python, vim, etc.)

### 4. App Launcher / Display
- **Purpose**: UI for interacting with the system
- **Runs**: Only when actively using
- **Features**:
  - Open apps (calendar, terminal, files)
  - Display container output
  - Show peer status
  - Sync status display

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         THE APP                                   │
│                                                                  │
│   ┌───────────────────────────────────────────────────────────┐ │
│   │  PEER DISCOVERY SERVICE (Background)                      │ │
│   │  • Finds other devices on network                        │ │
│   │  • Runs always, even when app "closed"                   │ │
│   │  • Audio/RF discovery later                             │ │
│   └───────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│   ┌───────────────────────────────────────────────────────────┐ │
│   │  SYNC ENGINE (Background)                                │ │
│   │  • Syncs files with discovered peers                     │ │
│   │  • Runs always                                          │ │
│   │  • Handles conflicts                                    │ │
│   └───────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│   ┌───────────────────────────────────────────────────────────┐ │
│   │  CONTAINER WITH YOUR LINUX OS (Background)                 │ │
│   │  • Your Alpine/Debian environment                        │ │
│   │  • Your files, configs, terminal                         │ │
│   │  • All your tools (git, python, vim, etc.)              │ │
│   │  • Runs always - like a background service               │ │
│   └───────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              ▼                                   │
│   ┌───────────────────────────────────────────────────────────┐ │
│   │  APP LAUNCHER / DISPLAY                                  │ │
│   │  • Open calendar, terminal, files                        │ │
│   │  • Display container output to screen                   │ │
│   │  • Only needed when you're actively using               │ │
│   └───────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation

### Technology Stack
- **Language**: Python 3.10+
- **Container**: Docker SDK for Python
- **Discovery**: zeroconf (mDNS), socket broadcasting
- **Sync**: rsync-like delta algorithm
- **UI**: Tkinter (desktop), future: mobile

### Module Structure
```
src/
├── core/
│   ├── __init__.py
│   ├── config.py          # Configuration management
│   ├── events.py          # Event system for inter-service communication
│   └── logger.py          # Logging setup
├── services/
│   ├── __init__.py
│   ├── discovery.py       # Peer Discovery Service
│   └── sync.py            # Sync Engine
├── container/
│   ├── __init__.py
│   └── manager.py         # Container lifecycle management
├── ui/
│   ├── __init__.py
│   ├── launcher.py        # App Launcher / Display
│   └── components.py      # Reusable UI components
└── main.py                # Entry point
```

## User Flow

1. **Host OS boots**
2. **App starts in background**
   - Peer Discovery starts (finds laptop if online)
   - Sync Engine starts (gets latest files)
   - Container starts (your OS boots)
3. **User opens apps** (terminal, calendar, files...)
4. **Host OS is now irrelevant** - everything runs in the cloud OS

## Future Enhancements
- Mobile support (phone)
- Audio-based discovery
- RF-based discovery
- End-to-end encryption
- Distributed file system
