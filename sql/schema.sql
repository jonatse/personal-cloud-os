-- Personal Cloud OS - Database Schema
-- MariaDB as the foundation for "Database as OS" vision
-- All conversations stored verbatim, tied to identity

-- =============================================================================
-- IDENTITY TABLES
-- =============================================================================

-- Core identity: platform-agnostic, tied to your thinking/voice
CREATE TABLE IF NOT EXISTS identities (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    uuid CHAR(36) NOT NULL UNIQUE,  -- Reticulum-style UUID
    display_name VARCHAR(255),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    personality JSON,  -- Tone, preferences, style
    active BOOLEAN DEFAULT TRUE,
    
    -- For importing/exporting identity to other AI platforms
    export_token VARCHAR(512),
    
    INDEX idx_uuid (uuid),
    INDEX idx_active (active)
);

-- =============================================================================
-- CONVERSATION TABLES
-- =============================================================================

-- All messages, verbatim, forever - enables auditing and reporting
CREATE TABLE IF NOT EXISTS conversation_messages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,  -- Tied to your identity
    
    session_id VARCHAR(64),
    message_index INT,
    
    role ENUM('user', 'assistant', 'system') NOT NULL,
    content LONGTEXT NOT NULL,  -- Full verbatim
    
    -- Metadata for auditing/reporting
    model_used VARCHAR(128),
    provider VARCHAR(64),
    token_count INT,
    tool_calls JSON,
    tools_used JSON,  -- Simplified tool list
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (identity_id) REFERENCES identities(id),
    INDEX idx_identity_session (identity_id, session_id),
    INDEX idx_identity_created (identity_id, created_at),
    INDEX idx_session (session_id)
);

-- Session metadata
CREATE TABLE IF NOT EXISTS sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    session_id VARCHAR(64) NOT NULL UNIQUE,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME NULL,
    platform VARCHAR(64),  -- 'cli', 'telegram', 'whatsapp', 'kilo', 'claude', etc.
    title VARCHAR(255),
    message_count INT DEFAULT 0,
    summary TEXT,  -- Auto-generated summary
    
    FOREIGN KEY (identity_id) REFERENCES identities(id),
    INDEX idx_identity_started (identity_id, started_at)
);

-- =============================================================================
-- DATA CATEGORIES (from VISION.md)
-- =============================================================================

-- Identity & Security
CREATE TABLE IF NOT EXISTS reticulum_identities (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    hash VARCHAR(128) NOT NULL,  -- RNS identity hash
    public_key TEXT,
    private_key_encrypted TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (identity_id) REFERENCES identities(id)
);

CREATE TABLE IF NOT EXISTS trust_list (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    trusted_identity_hash VARCHAR(128),
    petname VARCHAR(255),  -- Human-readable alias
    trust_level ENUM('known', 'trusted', 'verified'),
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (identity_id) REFERENCES identities(id)
);

-- PIM (Personal Information Management)
CREATE TABLE IF NOT EXISTS contacts (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    name VARCHAR(255) NOT NULL,
    aliases JSON,  -- Petnames, nicknames
    organization VARCHAR(255),
    emails JSON,
    phones JSON,
    addresses JSON,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (identity_id) REFERENCES identities(id)
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    start_at DATETIME NOT NULL,
    end_at DATETIME,
    recurrence JSON,  -- RRULE format
    location VARCHAR(255),
    attendees JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (identity_id) REFERENCES identities(id),
    INDEX idx_identity_start (identity_id, start_at)
);

CREATE TABLE IF NOT EXISTS tasks (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    status ENUM('pending', 'in_progress', 'completed', 'cancelled') DEFAULT 'pending',
    due_at DATETIME,
    completed_at DATETIME,
    priority INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (identity_id) REFERENCES identities(id)
);

-- Communication (LXMF, bridged SMS/email)
CREATE TABLE IF NOT EXISTS messages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    thread_id VARCHAR(128),
    
    sender_type ENUM('self', 'contact', 'external'),
    sender_identifier VARCHAR(255),
    
    direction ENUM('inbound', 'outbound'),
    content TEXT NOT NULL,
    attachments JSON,
    
    protocol VARCHAR(64),  -- 'lxmf', 'sms', 'mms', 'email', 'telegram', etc.
    metadata JSON,
    
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    delivered_at DATETIME,
    read_at DATETIME,
    
    FOREIGN KEY (identity_id) REFERENCES identities(id),
    INDEX idx_identity_thread (identity_id, thread_id),
    INDEX idx_sent_at (sent_at)
);

-- Media & Files
CREATE TABLE IF NOT EXISTS files (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    
    filename VARCHAR(255) NOT NULL,
    filepath VARCHAR(512),  -- Local path
    filehash VARCHAR(128),  -- SHA256
    mime_type VARCHAR(128),
    size_bytes BIGINT,
    
    category ENUM('image', 'video', 'audio', 'document', 'other'),
    tags JSON,
    metadata JSON,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    modified_at DATETIME,
    FOREIGN KEY (identity_id) REFERENCES identities(id)
);

-- Sensor Telemetry (from devices)
CREATE TABLE IF NOT EXISTS sensor_readings (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    device_id VARCHAR(64),
    
    sensor_type VARCHAR(64),  -- 'accelerometer', 'gps', 'battery', etc.
    value JSON NOT NULL,  -- Flexible for different sensor types
    unit VARCHAR(32),
    
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (identity_id) REFERENCES identities(id),
    INDEX idx_identity_sensor (identity_id, sensor_type, recorded_at)
);

-- Device & Mesh State
CREATE TABLE IF NOT EXISTS devices (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    
    device_uuid VARCHAR(64) NOT NULL,
    name VARCHAR(255),
    platform VARCHAR(64),  -- 'linux', 'android', etc.
    capabilities JSON,
    
    last_seen_at DATETIME,
    status ENUM('online', 'offline', 'sleep') DEFAULT 'offline',
    
    FOREIGN KEY (identity_id) REFERENCES identities(id),
    UNIQUE KEY idx_device_uuid (device_uuid)
);

CREATE TABLE IF NOT EXISTS mesh_links (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    
    local_device_id VARCHAR(64),
    remote_device_id VARCHAR(64),
    
    link_quality FLOAT,
    latency_ms INT,
    bandwidth_kbps INT,
    
    established_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_checked_at DATETIME,
    
    FOREIGN KEY (identity_id) REFERENCES identities(id)
);

-- Application Data
CREATE TABLE IF NOT EXISTS app_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    
    app_name VARCHAR(64) NOT NULL,
    data_type VARCHAR(64) NOT NULL,
    data JSON NOT NULL,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (identity_id) REFERENCES identities(id),
    INDEX idx_identity_app (identity_id, app_name, data_type)
);

-- =============================================================================
-- REPORTING & SUMMARIES
-- =============================================================================

-- Auto-generated summaries (can be regenerated from raw data)
CREATE TABLE IF NOT EXISTS summaries (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    
    period_type ENUM('hourly', 'daily', 'weekly', 'monthly') NOT NULL,
    period_start DATETIME NOT NULL,
    period_end DATETIME NOT NULL,
    
    summary_text TEXT NOT NULL,
    message_count INT,
    topics JSON,  -- Extracted topics
    
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (identity_id) REFERENCES identities(id),
    UNIQUE KEY idx_identity_period (identity_id, period_type, period_start)
);

-- =============================================================================
-- UTILITY
-- =============================================================================

-- Full-text search index
CREATE TABLE IF NOT EXISTS message_fts (
    id BIGINT PRIMARY KEY,
    content TEXT NOT NULL,
    FOREIGN KEY (id) REFERENCES conversation_messages(id) ON DELETE CASCADE
);

-- Note: Add FULLTEXT index after table creation:
-- ALTER TABLE message_fts ADD FULLTEXT INDEX idx_fts_content (content);
