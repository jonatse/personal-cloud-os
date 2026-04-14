-- Personal Cloud OS - Database Schema
-- Database as OS - Identity and Conversation Storage
-- 
-- This schema provides:
-- - Identity persistence across platforms (platform-agnostic context)
-- - Verbatim message storage for auditing and accuracy verification
-- - Session tracking across all conversations
--
-- Usage: mariadb -u root -p pcos < schema.sql

-- Create database if not exists
CREATE DATABASE IF NOT EXISTS pcos;
USE pcos;

-- =============================================================================
-- Identity Table - Your persistent identity across all platforms
-- =============================================================================
CREATE TABLE IF NOT EXISTS identities (
    id BIGINT AUTO_INCREMENT PRIMARY KEY KEY,
    uuid CHAR(36) NOT NULL UNIQUE COMMENT 'Reticulum-style UUID',
    display_name VARCHAR(255),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    personality JSON COMMENT 'Tone, preferences, communication style',
    active BOOLEAN DEFAULT TRUE,
    
    INDEX idx_uuid (uuid),
    INDEX idx_active (active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================================================================
-- Session Table - Track all conversation sessions
-- =============================================================================
CREATE TABLE IF NOT EXISTS sessions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    session_id VARCHAR(64) NOT NULL UNIQUE,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME NULL,
    platform VARCHAR(64) COMMENT 'cli, telegram, whatsapp, kilo, claude, etc.',
    message_count INT DEFAULT 0,
    summary TEXT COMMENT 'Auto-generated session summary',
    
    FOREIGN KEY (identity_id) REFERENCES identities(id)
        ON DELETE CASCADE,
    INDEX idx_identity_started (identity_id, started_at),
    INDEX idx_platform (platform)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================================================================
-- Conversation Messages - ALL messages stored verbatim forever
-- =============================================================================
CREATE TABLE IF NOT EXISTS conversation_messages (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    identity_id BIGINT NOT NULL,
    session_id VARCHAR(64) NOT NULL,
    message_index INT NOT NULL,
    
    -- Message content
    role ENUM('user', 'assistant', 'system') NOT NULL,
    content LONGTEXT NOT NULL COMMENT 'Full verbatim content',
    
    -- Metadata for auditing and reporting
    model_used VARCHAR(128),
    provider VARCHAR(64),
    token_count INT,
    tool_calls JSON COMMENT 'Tool calls made during this message',
    metadata JSON COMMENT 'Additional context (timestamp, etc.)',
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (identity_id) REFERENCES identities(id)
        ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        ON DELETE CASCADE,
        
    INDEX idx_identity_session (identity_id, session_id, message_index),
    INDEX idx_identity_created (identity_id, created_at),
    INDEX idx_role (role),
    INDEX idx_model (model_used)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =============================================================================
-- Identity Management Procedures
-- =============================================================================

-- Create a new identity
DELIMITER //
CREATE PROCEDURE create_identity(
    IN p_uuid CHAR(36),
    IN p_display_name VARCHAR(255),
    IN p_personality JSON
)
BEGIN
    INSERT INTO identities (uuid, display_name, personality)
    VALUES (p_uuid, p_display_name, p_personality);
    SELECT LAST_INSERT_ID() AS identity_id;
END //
DELIMITER ;

-- Get or create default identity
DELIMITER //
CREATE PROCEDURE get_or_create_default_identity()
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN END;
    
    SELECT id, uuid, display_name, personality, active
    FROM identities
    WHERE active = TRUE
    ORDER BY created_at ASC
    LIMIT 1;
END //
DELIMITER ;

-- =============================================================================
-- Session Management Procedures
-- =============================================================================

-- Start a new session
DELIMITER //
CREATE PROCEDURE start_session(
    IN p_identity_id BIGINT,
    IN p_session_id VARCHAR(64),
    IN p_platform VARCHAR(64)
)
BEGIN
    INSERT INTO sessions (identity_id, session_id, platform)
    VALUES (p_identity_id, p_session_id, p_platform);
END //
DELIMITER ;

-- End a session
DELIMITER //
CREATE PROCEDURE end_session(
    IN p_session_id VARCHAR(64),
    IN p_summary TEXT
)
BEGIN
    UPDATE sessions 
    SET ended_at = CURRENT_TIMESTAMP,
        summary = p_summary,
        message_count = (
            SELECT COUNT(*) FROM conversation_messages 
            WHERE session_id = p_session_id
        )
    WHERE session_id = p_session_id;
END //
DELIMITER ;

-- =============================================================================
-- Message Storage Procedures
-- =============================================================================

-- Store a message
DELIMITER //
CREATE PROCEDURE store_message(
    IN p_identity_id BIGINT,
    IN p_session_id VARCHAR(64),
    IN p_message_index INT,
    IN p_role ENUM('user', 'assistant', 'system'),
    IN p_content LONGTEXT,
    IN p_model_used VARCHAR(128),
    IN p_provider VARCHAR(64),
    IN p_token_count INT,
    IN p_tool_calls JSON,
    IN p_metadata JSON
)
BEGIN
    INSERT INTO conversation_messages (
        identity_id, session_id, message_index,
        role, content, model_used, provider, 
        token_count, tool_calls, metadata
    )
    VALUES (
        p_identity_id, p_session_id, p_message_index,
        p_role, p_content, p_model_used, p_provider,
        p_token_count, p_tool_calls, p_metadata
    );
END //
DELIMITER ;

-- =============================================================================
-- Reporting and Auditing Queries
-- =============================================================================

-- Get conversation summary for a session
DELIMITER //
CREATE PROCEDURE get_session_summary(IN p_session_id VARCHAR(64))
BEGIN
    SELECT 
        s.session_id,
        s.platform,
        s.started_at,
        s.ended_at,
        s.message_count,
        s.summary,
        COUNT(CASE WHEN cm.role = 'user' THEN 1 END) AS user_messages,
        COUNT(CASE WHEN cm.role = 'assistant' THEN 1 END) AS assistant_messages,
        SUM(cm.token_count) AS total_tokens
    FROM sessions s
    LEFT JOIN conversation_messages cm ON s.session_id = cm.session_id
    WHERE s.session_id = p_session_id
    GROUP BY s.id;
END //
DELIMITER ;

-- Get all messages for a session (verbatim)
DELIMITER //
CREATE PROCEDURE get_session_messages(IN p_session_id VARCHAR(64))
BEGIN
    SELECT message_index, role, content, model_used, provider, created_at
    FROM conversation_messages
    WHERE session_id = p_session_id
    ORDER BY message_index;
END //
DELIMITER ;

-- Verify summary against raw messages
DELIMITER //
CREATE PROCEDURE verify_session_summary(IN p_session_id VARCHAR(64))
BEGIN
    SELECT 
        s.summary AS stored_summary,
        COUNT(cm.id) AS actual_message_count,
        GROUP_CONCAT(
            CONCAT(cm.role, ': ', LEFT(cm.content, 50))
            ORDER BY cm.message_index
            SEPARATOR ' | '
        ) AS message_preview
    FROM sessions s
    JOIN conversation_messages cm ON s.session_id = cm.session_id
    WHERE s.session_id = p_session_id
    GROUP BY s.id;
END //
DELIMITER ;

-- Get identity's full conversation history
DELIMITER //
CREATE PROCEDURE get_identity_history(
    IN p_identity_id BIGINT,
    IN p_limit INT
)
BEGIN
    SELECT 
        s.session_id,
        s.platform,
        s.started_at,
        s.ended_at,
        s.message_count,
        s.summary
    FROM sessions s
    WHERE s.identity_id = p_identity_id
    ORDER BY s.started_at DESC
    LIMIT p_limit;
END //
DELIMITER ;

-- Export identity (portable)
DELIMITER //
CREATE PROCEDURE export_identity(IN p_identity_id BIGINT)
BEGIN
    SELECT 
        i.uuid,
        i.display_name,
        i.personality,
        i.created_at,
        JSON_ARRAYAGG(
            JSON_OBJECT(
                'session_id', s.session_id,
                'platform', s.platform,
                'started_at', s.started_at,
                'message_count', s.message_count
            )
        ) AS sessions
    FROM identities i
    LEFT JOIN sessions s ON i.id = s.identity_id
    WHERE i.id = p_identity_id
    GROUP BY i.id;
END //
DELIMITER ;