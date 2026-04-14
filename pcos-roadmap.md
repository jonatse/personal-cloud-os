# PCOS Roadmap & TODO

> Centralized tracking for Personal Cloud OS goals
> Last updated: 2026-04-14

---

## Completed ✅

### Database Foundation
- [x] MariaDB running on Pangolin (password: `pcos`)
- [x] SQLite fallback for offline resilience
- [x] Unified storage layer (pcos_storage.py)
- [x] Database schema: identities, sessions, conversation_messages
- [x] Verbatim message capture (not just last 4)
- [x] User/assistant differentiation

### Session Persistence
- [x] _load_session_context() on startup
- [x] _save_session_context() on quit
- [x] Works across CLI and WhatsApp

---

## In Progress 🚧

### MariaDB on Thelio
- [ ] Get MariaDB to start on Thelio (permission/config issue)
- [ ] Replicate `pcos` database to Thelio
- [ ] Test connectivity from Pangolin to Thelio MariaDB

### Data Sync
- [ ] Build sync mechanism between Pangolin and Thelio
- [ ] Bidirectional or master/slave replication
- [ ] Decide: which machine is primary?

### Passwords & Security
- [ ] Create passwords/encryption table
- [ ] Key management for encryption
- [ ] Integration with .env files

---

## Not Started 📋

### Database-as-OS Expansion
- [ ] Skills storage in DB
- [ ] Configurations in DB
- [ ] Cron jobs in DB
- [ ] Full "Database as OS" - all state in MariaDB

### Identity System
- [ ] Multiple identities support
- [ ] Personality/persona persistence
- [ ] Cross-platform identity binding

### Hardware & Inference
- [ ] vLLM/llama.cpp on Thelio for local inference
- [ ] Route requests: local GPU → external API → cloud
- [ ] Make Thelio the primary, laptop as thin client

### Reticulum Integration
- [ ] Identity management in DB
- [ ] Device mesh sync
- [ ] GROUP destinations for device communication

---

## Architecture Goals

| Goal | Description |
|------|-------------|
| Local-first | Works offline without internet |
| Mesh-native | Device-to-device communication |
| Identity-first | Cryptographic identity, not accounts |
| Database as OS | All state in MariaDB |
| Graceful degradation | Full when connected, partial when not |

---

## Data Categories to Store

1. **Identity & Security** - Reticulum identities, keys, petnames
2. **PIM** - contacts, calendar, tasks, notes, passwords
3. **Communication** - messages, SMS, email
4. **Conversation** - all Hermes conversations (in progress ✓)
5. **Media & Files** - photos, videos, documents
6. **Device State** - hardware, link quality, inventory
7. **Skills** - skill definitions and configs
8. **Configuration** - all system configs
9. **Cron** - scheduled jobs and history

---

## References

- PCOS-VISION.md (detailed status)
- personal-cloud-architecture skill
- knowledge-nexus schema
