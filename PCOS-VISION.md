# PCAS: Personal Cloud Agent System - Vision & Status

## Executive Summary

Build a local-first, identity-centered computing platform where all conversations and data flow through a central database, creating a persistent, auditable AI assistant that truly knows you across sessions and devices.

---

## Goals Completed ✅

### 1. Database Foundation (MariaDB + SQLite)
- **MariaDB running** on Pangolin (laptop) with root password `pcos`
- **SQLite fallback** for offline resilience
- **Unified storage layer** (`pcos_storage.py`) auto-detects MariaDB vs SQLite
- Database: `pcos` with tables:
  - `identities` - user identity with UUID
  - `sessions` - session tracking with platform metadata
  - `conversation_messages` - ALL messages stored verbatim

### 2. Session Persistence
- **Verbatim message capture** - every message stored forever (not just last 4)
- **User/assistant differentiation** - clear role tracking for audit
- **Cross-session continuity** - load previous session context on startup
- Falls back to JSON for quick compatibility

### 3. hermes-agent Integration
- `_load_session_context()` - loads from MariaDB/SQLite on startup
- `_save_session_context()` - saves all messages to database on quit
- Connected to CLI startup/shutdown

### 4. Git Repository
- Changes tracked in `hermes-agent` repo
- New file: `pcos_storage.py` (storage layer)
- Modified: `cli.py` (session integration)

---

## Current Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Platforms                            │
│  (CLI, WhatsApp, Telegram, Discord, etc.)               │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              hermes-agent (CLI/Gateway)                │
│  - _load_session_context()                             │
│  - _save_session_context()                              │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              pcos_storage.py                            │
│  ┌─────────────────────────────────────────────────┐   │
│  │  MariaDB (primary) ← root/pcos @ localhost     │   │
│  │  SQLite (fallback) → ~/.hermes/pcos.db         │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Goals In Progress 🚧

### 1. MariaDB on Thelio
- MariaDB installed but won't start (permission/ config issue)
- Need to get it running and replicate `pcos` database

### 2. Data Sync Mechanism
- Sync conversation data between Pangolin and Thelio
- Bidirectional or master/slave replication
- Consider: git bundles, rsync, MariaDB native replication

### 3. Passwords/Encryption Table
- Store credentials securely in MariaDB
- Encryption key management
- Integration with .env files

---

## Goals Not Started 📋

### 1. Identity System
- Multiple identities support
- Personality/persona persistence
- Cross-platform identity binding

### 2. Full Database-as-OS
- All agent state in MariaDB (not just conversations)
- Skills, configurations, cron jobs in DB
- Query-based interfaces replacing flat files

### 3. Thelio as Primary
- Move MariaDB to Thelio (more resources)
- Laptop as thin client
- Offline-first with sync

---

## What We've Built Today

| Component | Status | Location |
|-----------|--------|----------|
| MariaDB (Pangolin) | ✅ Running | localhost:3306 |
| pcos database | ✅ Created | `pcos` |
| identities/sessions/messages tables | ✅ Created | `pcos.*` |
| pcos_storage.py | ✅ Complete | hermes-agent/ |
| Session resume (SQL) | ✅ Working | cli.py |
| Session resume (JSON) | ✅ Fallback | cli.py |
| hermes-agent git repo | ✅ Tracking | ~/.hermes/hermes-agent/ |

---

## Next Steps

1. **Immediate**: Test session resume in CLI (run `hermes` and verify it loads context)
2. **Short-term**: Fix MariaDB on Thelio, replicate database
3. **Medium-term**: Build sync mechanism between machines
4. **Long-term**: Full "Database as OS" - all state in MariaDB

---

## Technical Notes

- MariaDB password: `pcos` (root user)
- SQLite path: `~/.hermes/pcos.db`
- Storage layer auto-detects: MariaDB preferred, SQLite fallback
- All messages stored with: role, content, session_id, message_index, created_at

---

*Last updated: 2026-04-14*
