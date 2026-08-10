-- Фактическая сумма выкупа Trade-in, которую указывает ТТ после выбора
-- «Сделка состоялась». Для старых заявок и для «Сделка не состоялась» — NULL.
ALTER TABLE claims ADD COLUMN buyout_amount INTEGER;
