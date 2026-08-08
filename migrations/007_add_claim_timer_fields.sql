-- Таймер отсутствия ответа на заявку: когда заявку "взяли в работу" (вручную
-- через кнопку либо автоматически по первому сообщению админа в чате заявки),
-- и на какой стадии напоминаний (5/10/15 мин) она уже находится, чтобы не
-- слать повторные напоминания на каждом цикле опроса claim_timer_service.
ALTER TABLE claims ADD COLUMN taken_at TIMESTAMP;
ALTER TABLE claims ADD COLUMN taken_by INTEGER;
ALTER TABLE claims ADD COLUMN reminder_stage INTEGER DEFAULT 0;
