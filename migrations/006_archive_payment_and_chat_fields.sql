-- Дополнительные колонки в архиве заявок, чтобы архивация не теряла
-- trade-in payment_method / competitor_offer и признак chat_locked.
ALTER TABLE claims_archive ADD COLUMN payment_method TEXT;
ALTER TABLE claims_archive ADD COLUMN competitor_offer TEXT;
ALTER TABLE claims_archive ADD COLUMN chat_locked INTEGER NOT NULL DEFAULT 0;
