-- CONFIG CMS for /manage panel (additive only; does not alter claims).
CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bot_texts (
    key TEXT PRIMARY KEY,
    category TEXT NOT NULL DEFAULT 'common',
    value TEXT NOT NULL,
    default_value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS managed_files (
    key TEXT PRIMARY KEY,
    file_id TEXT,
    file_unique_id TEXT,
    file_name TEXT,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS trade_points (
    user_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS config_change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER,
    user_name TEXT,
    entity_type TEXT NOT NULL,
    entity_key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);

CREATE INDEX IF NOT EXISTS idx_config_change_log_changed_at ON config_change_log(changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_bot_texts_category ON bot_texts(category);
