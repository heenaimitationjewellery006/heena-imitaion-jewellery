-- ==============================================================================
-- HEENA IMITATION JEWELLERS - ABANDONED CARTS SCHEMA & AUTO-PURGE SUPPORT
-- ==============================================================================
-- Purpose:
-- 1. Temporarily stores cart data for logged-in users who abandon checkout.
-- 2. Sends reminder #1 at 24 hours.
-- 3. Sends final reminder #2 before 72 hours (3 days).
-- 4. Automatically purged after max 3 days to avoid database load.
-- ==============================================================================

CREATE TABLE IF NOT EXISTS abandoned_carts (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(150) UNIQUE NOT NULL,
    user_name VARCHAR(100),
    cart_json TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reminder_1_sent INT DEFAULT 0,
    reminder_2_sent INT DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_abandoned_carts_email ON abandoned_carts (user_email);
CREATE INDEX IF NOT EXISTS idx_abandoned_carts_updated_at ON abandoned_carts (updated_at);
