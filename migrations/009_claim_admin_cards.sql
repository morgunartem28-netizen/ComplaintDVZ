-- Карточки новых заявок у админов: message_id в личке, чтобы напоминания
-- таймера 5/10/15 мин уходили reply на исходную карточку (аксы / техника /
-- Trade-in / корректировка остатков) и после рестарта бота.
CREATE TABLE IF NOT EXISTS claim_admin_cards (
    claim_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (claim_id, chat_id)
);

CREATE INDEX IF NOT EXISTS idx_claim_admin_cards_claim_id ON claim_admin_cards(claim_id);
