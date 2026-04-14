---
name: todo-inbox
description: GTD TODO inbox management - capture, view, and process items
category: productivity
---

# TODO Inbox Skill

> GTD workflow: Capture → Process → Done

## What It Does

### 1. View Inbox
Show all items in TODO inbox (uncategorized):
```
/todo inbox
```
or
```
/todo list inbox
```

### 2. Add to Inbox
Capture new items directly to inbox:
```
/todo add Fix MariaDB on Thelio @thelio
/todo add Research vLLM options @thelio
/todo add Dec ide sync architecture @system
```

### 3. List by Context
Filter inbox by context tag:
```
/todo @thelio
/todo @database
/todo @system
/todo @network
```

### 4. Move to Category
Process an item - change its category:
```
/todo move 1 to project
/todo move 5 to next_action
/todo move 3 to waiting
```

### 5. Mark Done
Complete an item:
```
/todo done 1
/todo complete 3
```

### 6. Show Stats
Quick overview:
```
/todo stats
/todo summary
```

---

## Categories

| Category | Description |
|----------|------------|
| **inbox** | Raw input, uncategorized |
| **project** | Multiple steps, defined outcome |
| **next_action** | Single physical action |
| **waiting** | Waiting on someone else |
| **someday** | Someday/maybe |
| **reference** | Reference material |
| **done** | Completed |

---

## Context Tags

Use @ to tag location/type:
- `@thelio` - needs Thelio
- `@database` - MariaDB work
- `@system` - general system
- `@network` - networking
- `@security` - security
- `@laptop` - needs Pangolin

---

## Workflow

```
1. Capture: /todo add [ idea @context ]
2. View:   /todo inbox
3. Process:/todo move [id] to [category]
4. Done:   /todo done [id]
```

---

## Database

Reads from MariaDB `pcos.gtd_items` table.

---

## Examples

### Add raw idea
```
/todo add Maybe try llama.cpp for inference @thelio
```

### See what's @thelio
```
/todo @thelio
```

### Process item to project
```
/todo move 1 to project
```

### Mark complete
```
/todo done 2
```