-- Чат внутри заявки: история сообщений (текст/фото/системные события) + признак
-- ручной блокировки обсуждения после финального решения по заявке.
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id INTEGER NOT NULL,
    sender_id INTEGER,
    sender_role TEXT NOT NULL,
    message_type TEXT NOT NULL DEFAULT 'text',
    text TEXT,
    file_id TEXT,
    reply_to_message_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_claim_id ON chat_messages(claim_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_claim_created ON chat_messages(claim_id, created_at);

ALTER TABLE claims ADD COLUMN chat_locked INTEGER NOT NULL DEFAULT 0;
