---
name: pcos-database
description: Personal Cloud OS MariaDB database schema - GTD, PARA, knowledge tracking
category: devops
---

# PCOS Database Schema

> MariaDB database for Personal Cloud OS - all your data in one place

## Quick Start

```bash
# Connect
mariadb -u root -p"pcos" pcos

# List tables
SHOW TABLES;
```

## Tables Overview

| Table | Purpose |
|-------|---------|
| `identities` | User identity (1 row = you) |
| `sessions` | Session tracking (CLI, WhatsApp, etc.) |
| `conversation_messages` | ALL messages verbatim |
| `gtd_categories` | GTD workflow categories |
| `gtd_items` | Your task/TODO items |
| `para_categories` | PARA organizational categories |
| `para_items` | Organized content |
| `gtd_para_mapping` | How GTD ↔ PARA relate |
| `knowledge_assertions` | Facts we've learned |
| `contradictions` | Conflicting assertions |
| `redundancies` | Similar assertions |
| `todo_skill_queries` | Common todo-inbox queries |

## Core Tables

### identities
```sql
CREATE TABLE identities (
    id INT AUTO_INCREMENT PRIMARY KEY,
    uuid TEXT UNIQUE NOT NULL,
    display_name TEXT,
    personality TEXT,
    active INT DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

### sessions
```sql
CREATE TABLE sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    identity_id INT NOT NULL,
    session_id TEXT UNIQUE NOT NULL,
    platform TEXT,
    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
    ended_at TEXT,
    message_count INT DEFAULT 0,
    summary TEXT
);
```

### conversation_messages
```sql
CREATE TABLE conversation_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    identity_id INT NOT NULL,
    session_id TEXT NOT NULL,
    message_index INT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    model_used TEXT,
    provider TEXT,
    token_count INT,
    tool_calls TEXT,
    metadata TEXT
);
```

## GTD System

### gtd_categories (7 rows pre-populated)
- inbox, project, next_action, waiting, someday, reference, done

### gtd_items
```sql
CREATE TABLE gtd_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    identity_id INT NOT NULL,
    category VARCHAR(20) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    project_id INT,
    context VARCHAR(50),  -- @thelio, @database, @system, etc.
    due_date DATETIME,
    completed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
```

## PARA System

### para_categories (4 rows pre-populated)
- Projects, Areas, Resources, Archives

### para_items
```sql
CREATE TABLE para_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    identity_id INT NOT NULL,
    para_category VARCHAR(20) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT,
    link_url VARCHAR(500),
    status VARCHAR(20) DEFAULT 'active',
    gtd_project_id INT
);
```

## Knowledge Tracking

### knowledge_assertions
```sql
CREATE TABLE knowledge_assertions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    identity_id INT NOT NULL,
    assertion_text TEXT NOT NULL,
    source_session_id VARCHAR(255),
    source_type VARCHAR(20),
    confidence DECIMAL(3,2) DEFAULT 1.00,
    status VARCHAR(20) DEFAULT 'active',  -- active, superseded, contradicted, archived
    superseded_by INT
);
```

### contradictions
```sql
CREATE TABLE contradictions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    assertion_a_id INT NOT NULL,
    assertion_b_id INT NOT NULL,
    severity VARCHAR(20) DEFAULT 'potential',
    resolution TEXT,
    resolved_at DATETIME
);
```

### redundancies
```sql
CREATE TABLE redundancies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    assertion_a_id INT NOT NULL,
    assertion_b_id INT NOT NULL,
    similarity_score DECIMAL(4,3) DEFAULT 0.0,
    status VARCHAR(20) DEFAULT 'potential'
);
```

## Workflow

```
1. Start with inbox (category = 'inbox')
2. Process: move to project/next_action/waiting/someday/reference/done
3. Link GTD items to PARA categories for organization
```

## Password

- User: `root`
- Password: `pcos`
- Database: `pcos`

## Current Stats

```sql
SELECT table_name, table_rows 
FROM information_schema.tables 
WHERE table_schema = 'pcos';
```

Output:
- identities: 1
- sessions: 3
- conversation_messages: 39
- gtd_categories: 7
- gtd_items: 26
- para_categories: 4