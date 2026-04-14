# Personal Cloud OS - Vision Document

> **Version:** 1.0  
> **Date:** 2026-04-13  
> **Author:** Jonathan Soberg (with Hermes Agent)

---

## 1. Tagline

**Worship in work. Transformation through discipline.**

We build bridges between what you know and what you need to know. A personal computing platform that transforms scattered data into unified knowledge — owned completely by you, functional without the internet, and scalable across all your devices.

---

## 2. The Problem

### 2.1 The Scattered Life

Modern computing fragments our data across devices, clouds, and services:

- **Ideas** strike in the shower, on a walk — lost before breakfast
- **Projects** live in one app, progress in another, notes in a third
- **Finances** scattered across budgeting apps, bank websites, spreadsheets
- **Communications** siloed in email, messaging apps, social networks
- **Health data** from wearables stays on phones, never analyzed
- **Files** spread across devices with no unified search or sync
- **Identity** scattered across services we don't own or control

### 2.2 The Cloud Trap

Current solutions add complexity rather than reducing it:
- Subscription services for everything
- Vendor lock-in that makes leaving expensive
- Privacy concerns with third-party data handling
- Internet required for basic functionality
- Monthly costs that compound indefinitely

### 2.3 The Token Burden

AI assistants like me cost tokens per interaction. Every query, every code generation, every analysis uses external compute. While powerful, this creates:
- Ongoing costs that never stop
- Dependency on external providers
- Privacy implications of sending data to cloud APIs
- Limits on how much we can use AI to help

---

## 3. The Solution

### 3.1 Core Principles

1. **Local-First** — Everything works without internet
2. **Owner-Controlled** — Your data, your compute, your rules
3. **Graceful Degradation** — Lose a node, lose capability, not functionality  
4. **Database as OS** — Everything is data in MariaDB
5. **Reticulum-Native** — Mesh networking for when infrastructure fails
6. **Efficiency-First** — Small, lean programs that run on modest hardware

### 3.2 The Vision

A distributed, local-first computing platform where:
- All your machines work as one unified system
- You reduce/eliminate dependency on external LLM API providers
- The system functions even when offline
- All data lives in one place (MariaDB) regardless of device
- Each device contributes what it can, scales up when connected
- The interface is you (Hermes Agent) talking to the system

### 3.3 How It Reduces Token Costs

**Before:** Every question → external API → tokens spent

**After:**
- Simple task → local GPU (Thelio, free)
- Complex task → external API (kilo-free)
- Really big → Sonnet/Opus
- Pattern learned → code path instead of LLM

---

## 4. Hardware Stack

### 4.1 Current Devices

| Device | Specs | Role |
|--------|-------|------|
| **Pangolin** (Laptop) | AMD Ryzen 7 7840U, 30GB RAM, Radeon 780M iGPU | Client, runs Hermes Agent, primary interface |
| **Thelio** (Desktop) | i9-14900KS (28 cores), 125GB RAM, RTX 4080 SUPER 16GB | Server, GPU compute, heavy lifting |
| **Future: Phone** | ~4-8GB RAM | Mobile node, sensors, portable access |

### 4.2 Capability Matrix

| Capability | Pangolin (Offline) | Pangolin + Thelio |
|------------|--------------------|--------------------|
| Code generation | ❌ | ✅ (via Thelio) |
| File operations | ✅ | ✅ |
| Database queries | ✅ (local) | ✅ (synced) |
| Web search | ❌ (no network) | ✅ |
| Terminal commands | ✅ | ✅ |
| Memory/context | ✅ | ✅ |
| Model routing | ✅ | ✅ + local GPU |
| Reticulum networking | ✅ | ✅ |

---

## 5. Network Scenarios

The system adapts to any connectivity state:

> **Note:** MariaDB is the ONLY database. No SQLite, no alternatives. All data flows through MariaDB.

| Scenario | Internet | Mesh | Capabilities |
|----------|----------|------|--------------|
| **Offline** | ❌ | ❌ | Local only, run existing code, query local DB |
| **Internet only** | ✅ | ❌ | Web search, external AI providers |
| **Mesh only** | ❌ | ✅ | Device-to-device, local inference, shared resources |
| **Mixed** | ✅ | ✅ | Best of both worlds — route based on need |

---

## 6. Data Categories (All in One Database)

### 6.1 Identity & Security
- Reticulum identities and keypairs
- Petnames and aliases
- Trust lists and access control rules
- Public keys and certificates
- Passwords and encrypted secrets

### 6.2 Personal Information Management (PIM)
- Contacts (people and organizations)
- Calendar events and recurring appointments
- Tasks, to-dos, and reminders
- Notes, journal entries, and memos

### 6.3 Communication & Messaging
- LXMF / Reticulum messages and threads
- Bridged SMS / MMS / RCS history
- Bridged email (metadata, bodies, attachments)
- Group chats and channels
- Voice messages and call logs
- Notification history

### 6.4 Media & Files
- Photos and images (with metadata and tags)
- Videos and recordings
- Audio files and music library
- Documents, PDFs, spreadsheets, and text files
- Arbitrary user files and downloads
- File versioning and sync metadata

### 6.5 Sensor & Hardware Telemetry
- Accelerometer data and motion logs
- Gyroscope readings
- Magnetometer / compass data
- Barometer / pressure readings
- Ambient light sensor values
- Proximity sensor events
- Temperature (battery and ambient)
- Battery level, charge cycles, and power events
- GPS / location history (opt-in)
- Camera snapshots, thumbnails, and stream metadata
- Microphone audio levels (optional)
- Haptic / vibration events
- Wi-Fi, Bluetooth, and cellular signal logs

### 6.6 Device & Mesh State
- Live device inventory in the Reticulum mesh
- Hardware capability list per device
- Link quality, latency, and bandwidth metrics
- Power, sleep, and charging state of each device
- System logs and error reports

### 6.7 Application & Utility Data
- Calculator history and saved equations
- Browser bookmarks, history, and open tabs
- Finance / budget entries and transactions
- Shopping lists and recipes
- Health / fitness summaries
- Custom application module data

### 6.8 Global Metadata & Indexing
- Full-text search index across all data
- Tags, categories, and relationships between records
- Access control and sharing rules
- Timestamps, version history, and conflict resolution data

---

## 7. Database Schema

### 7.1 Existing Foundation (from knowledge-nexus)

The knowledge-nexus project already provides:
- **nodes** — Core content storage with categories and versioning
- **node_revisions** — Git-like history tracking
- **edges** — Relationships between nodes
- **node_links** — Hyperlinks with paragraph position
- **tags** — Categorization
- **sources** — Citation tracking

### 7.2 Extension Required

Additional tables for:
- Reticulum identities and keys
- Contacts, calendar, tasks
- Messages and communications
- Media metadata
- Sensor data streams
- Device state
- Sync tracking

---

## 8. Reticulum Integration

### 8.1 Device Introduction Flow

1. **Device A** has Reticulum, **Device B** doesn't
2. Device A shows QR/I2P address of its Identity
3. Device B navigates to it, receives Identity
4. Device B installs Reticulum, imports Identity
5. Both devices share keys and can communicate

### 8.2 Group Mesh

- Use **GROUP destination** for device mesh
- All devices announce to the group
- Any device can communicate with others

### 8.3 Capabilities

- **Identity** — Cryptographic identity (Curve25519 + Ed25519)
- **Destination Types** — SINGLE, GROUP, PLAIN, LINK
- **Announce** — Peer discovery via broadcast
- **Resource** — Built-in chunked file transfer

---

## 9. Sync Strategy

### 9.1 Git-Like Model

1. Each device has local MariaDB
2. Changes tracked with revision tables
3. On connect: exchange change logs, merge conflicts
4. Conflict resolution options:
   - Last-write-wins (automatic)
   - Manual merge (git-style)

### 9.2 Hierarchical Sync

- High-bandwidth devices → full sync
- Low-bandwidth (phone) → metadata/indices only
- On-demand fetch when needed

---

## 10. Model Routing

### 10.1 Routing Logic

1. **Simple task** → local GPU (Thelio, free)
2. **Complex task** → external API (kilo-free)
3. **Really big** → Sonnet/Opus
4. **Pattern learned** → code path instead of LLM

### 10.2 Evolution

- Pattern recognition identifies repeated queries
- Code generates routing logic automatically
- Code executes, returns data
- If confident → done
- If uncertain → LLM verification (minimal tokens)
- Future same questions use code only

---

## 11. Future Directions

### 11.1 Database as OS

Eventually:
- Replace Linux with MariaDB as the foundation
- Scripts become applications
- Everything is a query
- Strip away translation layers

### 11.2 Lower-Level Implementation

- Integrate models into the database
- Compile to C for efficiency
- Reduce interpreter layers
- Translate Reticulum to lower-level language

---

## 12. References

- Reticulum: https://github.com/markqvist/Reticulum
- knowledge-nexus: ~/github/knowledge-nexus/
- personal-cloud-architecture skill: ~/.hermes/skills/architecture/personal-cloud-architecture/

---

## Appendix: Network Topology Examples

### Example 1: Full Offline
```
Pangolin (offline)
├── Local DB (full)
├── Local code execution
└── No network access
```

### Example 2: Mesh Only
```
Pangolin ←──→ Thelio (via Reticulum)
    ↓              ↓
Local DB      Local DB
    ↓              ↓
Shared sync  Shared sync
```

### Example 3: Mixed
```
Internet ←──→ Pangolin ←──→ Thelio
              ↓            ↓
           Local DB    Local DB + GPU
              ↓            ↓
           Full sync   Full sync
```

---

*This document captures the vision as of 2026-04-13. It will evolve as the project develops.*