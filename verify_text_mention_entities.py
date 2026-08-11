"""Изолированная функциональная проверка text_mention entities.

Для каждого места, переписанного с markdown-ссылки build_user_link(...) на
aiogram.utils.formatting.Text(...) + build_user_mention(...), скрипт строит
тот же самый Text(...)-контент с тестовыми данными и проверяет:
  1. среди entities есть запись с type == "text_mention";
  2. вложенный user.id совпадает с ожидаемым user_id;
  3. offset/length корректно указывают на позицию имени в итоговом тексте
     (сверяется срез text[offset:offset+length], с учётом того, что offset и
     length в Bot API считаются в UTF-16 code units, а не в кодовых точках
     Python — это важно, т.к. эмодзи вроде "👤"/"🔄" перед упоминанием
     занимают 2 code unit, и наивная срезка по python-индексам была бы неверна).

Ничего не отправляет в Telegram и не обращается к боту/БД — только строит
Text(...)-деревья и проверяет их рендер через .as_kwargs()/.as_caption_kwargs().
"""
import asyncio
import sys

from aiogram.utils.formatting import Text, Bold, Italic

from utils.telegram_helpers import build_user_mention

TEST_USER_ID = 123456789
TEST_NAME = "Тест Тестов"

FAILURES = []


def utf16_slice(text: str, offset: int, length: int) -> str:
    """Срез текста по offset/length в UTF-16 code units (как считает Bot API)."""
    encoded = text.encode("utf-16-le")
    piece = encoded[offset * 2:(offset + length) * 2]
    return piece.decode("utf-16-le")


def check(label: str, kwargs: dict, expected_user_id: int = TEST_USER_ID, expected_name: str = TEST_NAME):
    text = kwargs.get("text") or kwargs.get("caption")
    entities = kwargs.get("entities") or kwargs.get("caption_entities") or []

    mention_entities = [e for e in entities if e.type == "text_mention"]
    if not mention_entities:
        FAILURES.append(f"[{label}] Нет ни одной entity text_mention среди {[e.type for e in entities]}")
        print(f"[FAIL] {label}: entity text_mention отсутствует")
        return

    matched = None
    for e in mention_entities:
        if e.user and e.user.id == expected_user_id:
            matched = e
            break

    if matched is None:
        found_ids = [e.user.id if e.user else None for e in mention_entities]
        FAILURES.append(f"[{label}] Ни одна text_mention entity не содержит user.id={expected_user_id} (найдены: {found_ids})")
        print(f"[FAIL] {label}: user.id не совпадает (найдены: {found_ids})")
        return

    sliced = utf16_slice(text, matched.offset, matched.length)
    if sliced != expected_name:
        FAILURES.append(
            f"[{label}] offset/length указывают на '{sliced}', ожидалось '{expected_name}' "
            f"(offset={matched.offset}, length={matched.length})"
        )
        print(f"[FAIL] {label}: text[offset:offset+length]='{sliced}' != '{expected_name}'")
        return

    print(f"[OK]   {label}: user.id={matched.user.id} offset={matched.offset} length={matched.length} "
          f"slice='{sliced}'")


def test_tradein_process_tradein_claim():
    display_id = "Т1"
    model, sim, memory, condition, battery = "iPhone 14", "Dual Sim", "128GB", "Как новый", "95%"
    repair, equipment, activation_date, target_model = "Без ремонтов", "Коробка, кабель", "01.01.2024", "iPhone 15"
    payment_method, competitor_offer, receiver_name = "Наличные", "Не оценивали", "Иванов И.И."

    content = Text(
        "🔄 ", Bold(f"НОВАЯ ЗАЯВКА (Trade-in) {display_id}"), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "👤 ", Bold("ТТ:"), " ", build_user_mention(TEST_USER_ID, TEST_NAME), "\n",
        "📱 ", Bold("Модель:"), " ", model, "\n",
        "📱 ", Bold("SIM:"), " ", sim, "\n",
        "💾 ", Bold("Память:"), " ", memory, "\n",
        "🔍 ", Bold("Состояние:"), " ", condition, "\n",
        "🔋 ", Bold("Аккумулятор:"), " ", battery, "\n",
        "🔧 ", Bold("Ремонт:"), " ", repair, "\n",
        "📦 ", Bold("Комплектация:"), " ", equipment, "\n",
        "📅 ", Bold("Активация:"), " ", activation_date, "\n",
        "🎯 ", Bold("Планирует взять:"), " ", target_model, "\n",
        "💳 ", Bold("Форма оплаты:"), " ", payment_method, "\n",
        "🥊 ", Bold("Предложение конкурента:"), " ", competitor_offer, "\n",
        "🧑‍💼 ", Bold("Принял устройство:"), " ", receiver_name, "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
    )
    check("handlers/tradein.py: process_tradein_claim (caption админам)", content.as_kwargs())


def test_technics_process_ptv_claim():
    display_id, client_name, device_name, imei = "А1", "Петров П.П.", "iPhone 13", "111222333444555"
    defect, mp_status, purchase_date, days_text, warranty_display = "Не включается", "Нет", "01.02.2024", "10 дней", "Предоставлен"

    content = Text(
        "📱 ", Bold(f"НОВАЯ ЗАЯВКА (ПТВ) {display_id}"), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "👤 ", Bold("Клиент:"), " ", client_name, "\n",
        "📱 ", Bold("Устройство:"), " ", device_name, "\n",
        "📱 ", Bold("IMEI:"), " ", imei, "\n",
        "📝 ", Bold("Дефект:"), "\n", Italic(defect), "\n",
        "🔧 ", Bold("Мех. повреждения:"), " ", mp_status, "\n",
        "📅 ", Bold("Дата покупки:"), " ", purchase_date, "\n",
        "⏳ ", Bold("Прошло:"), " ", days_text, "\n",
        "📄 ", Bold("Гарантийный талон:"), " ", warranty_display, "\n",
        "👤 ", Bold("ТТ:"), " ", build_user_mention(TEST_USER_ID, TEST_NAME),
    )
    check("handlers/technics.py: process_ptv_claim (request_text)", content.as_kwargs())


def test_technics_process_new_device_claim():
    display_id, device_name, imei, client_name = "Т2", "Samsung S23", "999888777666555", "Сидоров С.С."
    defect, purchase_date, days_text, action_text = "Треснул экран", "05.02.2024", "3 дня", "✅ Принять на Проверку Качества (ПК) (до 14 дней)"

    content = Text(
        "📱 ", Bold(f"НОВАЯ ЗАЯВКА (Новое устройство) {display_id}"), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "👤 ", Bold("ТТ:"), " ", build_user_mention(TEST_USER_ID, TEST_NAME), "\n",
        "📱 ", Bold("Устройство:"), " ", device_name, "\n",
        "📱 ", Bold("IMEI:"), " ", imei, "\n",
        "👤 ", Bold("Клиент:"), " ", client_name, "\n",
        "📝 ", Bold("Дефект:"), "\n", Italic(defect), "\n",
        "📅 ", Bold("Дата покупки:"), " ", purchase_date, "\n",
        "⏳ ", Bold("Прошло:"), " ", days_text, "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "📌 ", Bold("Автоматическое решение системы:"), "\n",
        action_text,
    )
    check("handlers/technics.py: process_new_device_claim (request_text)", content.as_kwargs())


def test_accessories_acc_wish_selected():
    display_id, client_name, nomenclature, date_sale = "В1", "Кузнецов К.К.", "Адаптер APPLE USB-C 20W", "10.02.2024"
    defect, wish_ru = "Не работает", "Возврат"

    content = Text(
        "🆕 ", Bold(f"НОВАЯ ЗАЯВКА (Аксессуар) {display_id}"), "\n\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "👤 ", Bold("ТТ:"), " ", build_user_mention(TEST_USER_ID, TEST_NAME), "\n",
        "👤 ", Bold("Сотрудник:"), " ", client_name, "\n",
        "📦 ", Bold("Номенклатура:"), " ", nomenclature, "\n",
        "📅 ", Bold("Дата продажи:"), " ", date_sale, "\n",
        "📝 ", Bold("Дефект:"), " ", defect, "\n",
        "💬 ", Bold("Требование клиента:"), " ", wish_ru, "\n\n",
    )
    check("handlers/accessories.py: acc_wish_selected (caption фото)", content.as_caption_kwargs())


def test_tech_adjustment_return_approver():
    display_id, nomenclature, imei, price = "С1", "iPhone 12", "IMEI отсутствует", "50000"
    purchase_date, refund_method, refund_date = "01.01.2024", "Карта", "15.02.2024"
    location, receipt, approver = "На ТТ", "Да", "Иванов"

    content = Text(
        f"Заявка {display_id}\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "ТТ: ", build_user_mention(TEST_USER_ID, TEST_NAME), "\n",
        "Просьба провести возврат\n",
        f"Покупали: {nomenclature} {imei}\n",
        f"Цена: {price}\n",
        f"Дата покупки: {purchase_date}\n",
        f"Способ возврата: {price} {refund_method}\n",
        f"Дата возврата: {refund_date}\n",
        f"Нахождение товара: {location}\n",
        f"Пробили чек и аннулировали: {receipt}\n",
        f"Согласовано: {approver}\n",
        "━━━━━━━━━━━━━━━━━━━━",
    )
    check("handlers/tech_adjustment.py: return_approver (template)", content.as_kwargs())


def test_tech_adjustment_exchange_approver():
    display_id, nomenclature, imei, price = "С2", "iPhone 11", "111", "40000"
    purchase_date, new_nomenclature, new_imei, new_price = "01.01.2024", "iPhone 13", "222", 55000.0
    diff_line, exchange_date, location, receipt, approver = "Доплатили: 15000 Картой", "20.02.2024", "У Ильгиза", "Нет", "Петров"

    content = Text(
        f"Заявка {display_id}\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "ТТ: ", build_user_mention(TEST_USER_ID, TEST_NAME), "\n",
        "Просьба провести обмен\n",
        f"Покупали: {nomenclature} {imei}\n",
        f"Цена: {price}\n",
        f"Дата покупки: {purchase_date}\n",
        f"Поменяли на: {new_nomenclature} {new_imei}\n",
        f"Цена новой техники: {new_price:.0f}\n",
        f"{diff_line}\n",
        f"Дата обмена: {exchange_date}\n",
        f"Нахождение товара: {location}\n",
        f"Пробили чек и аннулировали: {receipt}\n",
        f"Согласовано: {approver}\n",
        "━━━━━━━━━━━━━━━━━━━━",
    )
    check("handlers/tech_adjustment.py: exchange_approver (template)", content.as_kwargs())


def test_complaint_return_date_valid_old():
    display_id, nomenclature, price, purchase_date = "В5", "Адаптер", "1990", "01.01.2024"
    refund_method, refund_date, admin_name = "Наличные", "10.02.2024", "Смирнов"

    content = Text(
        f"Заявка {display_id}\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "Просьба провести возврат\n\n",
        "Торговая точка: ", build_user_mention(TEST_USER_ID, TEST_NAME), "\n",
        f"Покупали: {nomenclature}\n",
        f"Цена: {price}\n",
        f"Дата покупки: {purchase_date}\n",
        f"Способ возврата: {refund_method}\n",
        f"Дата возврата: {refund_date}\n",
        f"Согласовано: {admin_name}\n",
        "━━━━━━━━━━━━━━━━━━━━",
    )
    check("handlers/complaint.py: return_date_valid_old (template)", content.as_kwargs())


def test_complaint_exchange_receipt_voided_old():
    display_id, nomenclature, returned_price, purchase_date = "В6", "Чехол", 990.0, "01.01.2024"
    new_item, new_price, diff_line = "Кабель USB-C", 1490.0, "Доплатили: 500 Наличными"
    exchange_date, receipt_voided, approver = "12.02.2024", "Да", "Смирнов"

    content = Text(
        f"Заявка {display_id}\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "Просьба провести обмен\n\n",
        "Торговая точка: ", build_user_mention(TEST_USER_ID, TEST_NAME), "\n",
        f"Покупали: {nomenclature}\n",
        f"Цена: {returned_price:.0f}\n",
        f"Дата покупки: {purchase_date}\n",
        f"Позиция на обмен: {new_item}\n",
        f"Цена: {new_price:.0f}\n",
        f"{diff_line}\n",
        f"Дата обмена: {exchange_date}\n",
        f"Чек пробит и аннулирован: {receipt_voided}\n",
        f"Согласовано: {approver}\n",
        "━━━━━━━━━━━━━━━━━━━━",
    )
    check("handlers/complaint.py: exchange_receipt_voided_old (template)", content.as_kwargs())


def test_common_inline_search_claim():
    search_id, category_ru, client_text = "Т3", "Техника", "Николаев Н.Н."
    defect_text, date_text, wish_text = "Не заряжается", "01.03.2024", "Возврат"
    status_emoji, status_ru, admin_text, comment_text = "", "Одобрено", "Смирнов", "Всё ок"

    tt_node = build_user_mention(TEST_USER_ID, TEST_NAME)
    content = Text(
        f"Заявка {search_id}\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        f"Категория: {category_ru}\n",
        "ТТ: ", tt_node, "\n",
        f"Сотрудник: {client_text}\n",
        "Дефект:\n", Italic(defect_text), "\n",
        f"Дата покупки: {date_text}\n",
        f"Пожелание: {wish_text}\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        f"Решение: {status_emoji} {status_ru}\n",
        f"Ответственный: {admin_text}\n",
        f"Комментарий: {comment_text}\n",
    )
    check("handlers/common.py: inline_search_claim (result_text)", content.as_kwargs())


def test_super_admin_stats_pending():
    from aiogram.utils.formatting import Text as _Text, Bold as _Bold
    pending = [
        (1, "Т1", TEST_USER_ID, "tech", "ПТВ", "01.01.2024 10:00", TEST_NAME, None),
        (2, "А1", 987654321, "acc", "Аксессуар", "01.01.2024 11:00", None, "Второй Клиент"),
    ]
    parts = [_Bold("⏳ Просроченные заявки (без ответа > 2ч):"), "\n\n"]
    for pid, display_id, uid, cat, sub, created, tg_name, client_name in pending:
        tt_node = build_user_mention(uid, tg_name or client_name or str(uid)) if uid else "Не указано"
        parts.extend([
            f"🆔 {display_id} | ТТ: ", tt_node, f" | {cat}/{sub}\n 🕒 Создана: {created}\n\n"
        ])
    content = _Text(*parts)
    kwargs = content.as_kwargs()

    # Первая заявка — тестовый TEST_USER_ID/TEST_NAME (основная проверка).
    check("handlers/super_admin.py: stats_pending (заявка №1)", kwargs, TEST_USER_ID, TEST_NAME)
    # Вторая заявка — независимая проверка второй entity в том же сообщении
    # (несколько text_mention с разными offset в одном тексте).
    check("handlers/super_admin.py: stats_pending (заявка №2)", kwargs, 987654321, "Второй Клиент")


async def test_chat_render_history_content():
    """Интеграционная проверка реальной handlers.chat._render_history_content:
    несколько сообщений от автора заявки (роль 'tt') — каждое должно получить
    СВОЙ независимый text_mention с корректным offset/length."""
    from handlers.chat import _render_history_content

    claim = {
        'id': 1,
        'display_id': 'Т1',
        'user_id': TEST_USER_ID,
        'tg_name': TEST_NAME,
        'client_name': None,
    }
    messages = [
        {'message_type': 'text', 'sender_role': 'tt', 'text': 'Первое сообщение от ТТ',
         'created_at': '2024-01-01 10:00:00', 'reply_to_message_id': None},
        {'message_type': 'text', 'sender_role': 'admin', 'text': 'Ответ администратора',
         'created_at': '2024-01-01 10:05:00', 'reply_to_message_id': None},
        {'message_type': 'text', 'sender_role': 'tt', 'text': 'Второе сообщение от ТТ',
         'created_at': '2024-01-01 10:10:00', 'reply_to_message_id': None},
        {'message_type': 'system', 'text': 'Статус изменён: Одобрено',
         'created_at': '2024-01-01 10:15:00'},
    ]
    content = await _render_history_content(claim, messages)
    kwargs = content.as_kwargs()

    text = kwargs["text"]
    mention_entities = [e for e in kwargs["entities"] if e.type == "text_mention"]
    if len(mention_entities) != 2:
        FAILURES.append(
            f"[handlers/chat.py: _render_history_content] Ожидалось 2 entity text_mention "
            f"(по одной на каждое сообщение ТТ), найдено {len(mention_entities)}"
        )
        print(f"[FAIL] handlers/chat.py: _render_history_content: entities={len(mention_entities)} (ожидалось 2)")
    else:
        all_ok = True
        for i, e in enumerate(mention_entities, 1):
            sliced = utf16_slice(text, e.offset, e.length)
            ok = e.user.id == TEST_USER_ID and sliced == TEST_NAME
            all_ok = all_ok and ok
            print(f"  mention #{i}: user.id={e.user.id} offset={e.offset} length={e.length} slice='{sliced}' -> {'OK' if ok else 'FAIL'}")
            if not ok:
                FAILURES.append(f"[handlers/chat.py: _render_history_content] mention #{i} некорректна")
        print(f"[{'OK' if all_ok else 'FAIL'}]   handlers/chat.py: _render_history_content (2 сообщения ТТ)")


async def test_chat_reply_last_start_content():
    """Проверка конструкции контента из handlers.chat.chat_reply_last_start."""
    from aiogram.utils.formatting import Text as _Text, Italic as _Italic
    from handlers.chat import _sender_label_node

    claim = {'id': 1, 'display_id': 'Т1', 'user_id': TEST_USER_ID, 'tg_name': TEST_NAME, 'client_name': None}
    label_node = await _sender_label_node(claim, 'tt')
    quote = "Пример цитаты сообщения"
    content = _Text(
        "↩️ Ответ на сообщение от ", label_node, ":\n",
        _Italic(quote), "\n\nВведите текст ответа:",
    )
    check("handlers/chat.py: chat_reply_last_start (content)", content.as_kwargs())


async def test_notifications_decision():
    """Интеграционная проверка utils.notifications._resolve_point_mention_node
    + воспроизведение структуры Text(...) из notify_super_admins_of_decision."""
    from aiogram.utils.formatting import Text as _Text, Bold as _Bold
    from utils.notifications import _resolve_point_mention_node

    point_node = await _resolve_point_mention_node(TEST_USER_ID, TEST_NAME)
    category_label, admin_name, decision, timestamp, comment = "Техника", "Смирнов", "Одобрено", "01.01.2024 12:00", "Всё ок"
    admin_id = 999001
    item, status = "iPhone 12", "approved"
    admin_node = build_user_mention(admin_id, admin_name)

    content = _Text(
        "🔔 ", _Bold("Решение по заявке Т1"), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        "📂 ", _Bold("Тип:"), " ", category_label, "\n",
        "📦 ", _Bold("Товар:"), " ", item, "\n",
        "🏢 ", _Bold("Точка (ТТ):"), " ", point_node, "\n",
        "📌 ", _Bold("Решение:"), " ", decision, "\n",
        "📋 ", _Bold("Статус:"), " ", status, "\n",
        "🕒 ", _Bold("Дата:"), " ", timestamp, "\n",
        "💬 ", _Bold("Комментарий:"), " ", (comment if comment else "—"), "\n",
        "━━━━━━━━━━━━━━━━━━━━\n",
        _Bold("Решение принял:"), "\n",
        "👤 ", admin_node,
    )
    check(
        "utils/notifications.py: notify_super_admins_of_decision (content)",
        content.as_kwargs(),
        expected_user_id=TEST_USER_ID,
    )
    # В уведомлении два text_mention: ТТ + администратор
    mention_entities = [e for e in content.as_kwargs()["entities"] if e.type == "text_mention"]
    admin_ids = [e.user.id for e in mention_entities if e.user]
    if admin_id not in admin_ids:
        FAILURES.append(
            f"[utils/notifications.py] Ожидался text_mention admin_id={admin_id}, "
            f"найдены: {admin_ids}"
        )
        print(f"[FAIL] notifications admin mention: admin_id={admin_id} не в {admin_ids}")
    else:
        print(f"[OK]   notifications: text_mention для админа id={admin_id} присутствует")


def test_tradein_approve_finish_content():
    """Проверка Text(...) уведомления сотруднику при одобрении Trade-in
    (Ответственный — TextMention по admin_id)."""
    from aiogram.utils.formatting import Text as _Text, Bold as _Bold

    price, admin_name, admin_id = "15000", "Artem", 358530649
    content = _Text(
        "✅ ", _Bold("Заявка одобрена!"), "\n\n",
        "💰 ", _Bold("Стоимость выкупа:"), " ", price, "\n",
        "👨‍💼 ", _Bold("Ответственный:"), " ", build_user_mention(admin_id, admin_name), "\n\n",
        "📎 ", _Bold("Требуется подписать договор купли-продажи Trade-in"), "\n",
        "Файл договора и инструкция по заполнению — в следующих сообщениях.\n\n",
        "Когда сделка будет завершена, отметьте итог кнопкой ниже "
        "(«Сделка состоялась» или «Сделка не состоялась»):",
    )
    check(
        "handlers/tradein.py: tradein_admin_approve_finish (user notify)",
        content.as_kwargs(),
        expected_user_id=admin_id,
        expected_name=admin_name,
    )


def main():
    test_tradein_process_tradein_claim()
    test_technics_process_ptv_claim()
    test_technics_process_new_device_claim()
    test_accessories_acc_wish_selected()
    test_tech_adjustment_return_approver()
    test_tech_adjustment_exchange_approver()
    test_complaint_return_date_valid_old()
    test_complaint_exchange_receipt_voided_old()
    test_common_inline_search_claim()
    test_super_admin_stats_pending()

    asyncio.run(test_chat_render_history_content())
    asyncio.run(test_chat_reply_last_start_content())
    asyncio.run(test_notifications_decision())
    test_tradein_approve_finish_content()

    print()
    if FAILURES:
        print(f"ИТОГО: {len(FAILURES)} ОШИБОК")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    else:
        print("ИТОГО: все проверки пройдены успешно.")


if __name__ == "__main__":
    main()
