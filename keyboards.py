from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

def get_main_menu():
    # «Запрос на корректировку остатков» временно скрыт из меню (бизнес-логика
    # handlers/complaint.py, handlers/tech_adjustment.py и callback'и остаются
    # в коде — функционал можно вернуть, снова добавив кнопку сюда).
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Техника"), KeyboardButton(text="Аксессуар")],
            [KeyboardButton(text="Trade-in")],
        ],
        resize_keyboard=True
    )
    return kb

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

def get_tech_type_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠 ПТВ", callback_data="tech_ptv")],
        [InlineKeyboardButton(text="🆕 Новое устройство", callback_data="tech_new")]
    ])
    return kb

def get_mp_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data="mp_yes")],
        [InlineKeyboardButton(text="Нет", callback_data="mp_no")]
    ])
    return kb

def get_wish_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Возврат", callback_data="wish_return"), InlineKeyboardButton(text="🔄 Обмен", callback_data="wish_exchange")]
    ])
    return kb

def get_admin_decision(claim_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"adm_approve_{claim_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_reject_{claim_id}")]
    ])
    return kb

def get_tradein_admin_decision(claim_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"adm_tradein_approve_{claim_id}")],
        [InlineKeyboardButton(text="❌ Отказать", callback_data=f"adm_tradein_reject_{claim_id}")]
    ])
    return kb

def get_super_admin_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👮 Назначить админа", callback_data="sa_add_admin_menu")],
        [InlineKeyboardButton(text="🗑 Удалить админа", callback_data="sa_del_admin_menu")],
        [InlineKeyboardButton(text="📋 Список админов", callback_data="sa_list_admins")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="sa_stats_menu")],
        [InlineKeyboardButton(text="🧹 Очистить БД", callback_data="sa_clear_db")]
    ])
    return kb


def get_admin_panel_quick_actions():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назначить админа", callback_data="sa_add_admin_menu")],
        [InlineKeyboardButton(text="Снять права", callback_data="sa_del_admin_menu")],
        [InlineKeyboardButton(text="Список админов", callback_data="sa_list_admins")],
        [InlineKeyboardButton(text="Статистика", callback_data="sa_stats_menu")],
        [InlineKeyboardButton(text="Расширенное меню", callback_data="sa_open_full_menu")]
    ])
    return kb

def get_role_selection_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠 Техника (admin_tech)", callback_data="role_tech")],
        [InlineKeyboardButton(text="🎧 Аксессуары (admin_acc)", callback_data="role_acc")],
        [InlineKeyboardButton(text="🔄 Trade-in (admin_tradein)", callback_data="role_tradein")],
        [InlineKeyboardButton(text="📦 Остатки (admin_complaint)", callback_data="role_complaint")],
        [InlineKeyboardButton(text="👑 Супер-админ (super_admin)", callback_data="role_super")]
    ])
    return kb

def get_stats_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Общая статистика", callback_data="stats_overview")],
        [InlineKeyboardButton(text="🏢 Подробно по ТТ", callback_data="stats_points")],
        [InlineKeyboardButton(text="⏳ Просроченные заявки", callback_data="stats_pending")],
        [InlineKeyboardButton(text="📅 Экспорт за период", callback_data="stats_export_period_menu")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]
    ])
    return kb


def get_export_period_buttons(back_callback: str = "sa_stats_menu"):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="За 7 дней", callback_data="stats_export_days_7")],
        [InlineKeyboardButton(text="За 30 дней", callback_data="stats_export_days_30")],
        [InlineKeyboardButton(text="За всё время", callback_data="stats_export_days_all")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback)]
    ])
    return kb

def get_stats_pagination(page: int, total_pages: int):
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"stats_page_{page-1}"))
    buttons.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="stats_current"))
    if page < total_pages - 1:
        buttons.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"stats_page_{page+1}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        buttons,
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="sa_stats_menu")]
    ])

def get_warranty_status_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Прикрепить фото талона", callback_data="warranty_photo")],
        [InlineKeyboardButton(text="❌ Талон утерян", callback_data="warranty_lost")]
    ])
    return kb

def get_back_to_admin():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню админа", callback_data="back_to_admin")]
    ])
    return kb

# ==========================================
# КЛАВИАТУРЫ ДЛЯ COMPLAINT
# ==========================================

def get_stock_adjustment_request_buttons(claim_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отправить запрос", callback_data=f"acc_stock_request_{claim_id}")],
        [InlineKeyboardButton(text="Вернуться в начало", callback_data="acc_stock_back")]
    ])
    return kb

def get_complaint_admin_keyboard(claim_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Обработано", callback_data=f"complaint_processed_{claim_id}")]
    ])
    return kb

def get_refund_method_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Карта", callback_data="refund_card")],
        [InlineKeyboardButton(text="Наличные", callback_data="refund_cash")]
    ])
    return kb

# ==========================================
# НОВЫЕ КЛАВИАТУРЫ ДЛЯ COMPLAINT (ВОЗВРАТ/ОБМЕН)
# ==========================================

def get_adjustment_type_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Корректировка техники", callback_data="adj_tech")],
        [InlineKeyboardButton(text="Корректировка аксессуаров", callback_data="adj_acc")],
        [InlineKeyboardButton(text="Вернуться в начало", callback_data="acc_stock_back")]
    ])
    return kb

def get_return_or_exchange_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Возврат", callback_data="choose_return")],
        [InlineKeyboardButton(text="Обмен", callback_data="choose_exchange")],
        [InlineKeyboardButton(text="Вернуться в начало", callback_data="acc_stock_back")]
    ])
    return kb

def get_receipt_voided_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data="receipt_yes")],
        [InlineKeyboardButton(text="Нет", callback_data="receipt_no")]
    ])
    return kb

def get_diff_method_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Карта", callback_data="diff_card")],
        [InlineKeyboardButton(text="Наличные", callback_data="diff_cash")]
    ])
    return kb

def get_item_location_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="На ТТ", callback_data="loc_tt")],
        [InlineKeyboardButton(text="У Ильгиза", callback_data="loc_ilgiz")]
    ])
    return kb

def get_imei_missing_button(callback_data: str = "imei_missing"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="IMEI отсутствует", callback_data=callback_data)]
    ])

# ==========================================
# КЛАВИАТУРЫ ДЛЯ ПОДТЯГИВАНИЯ ДАННЫХ ИЗ ЗАЯВКИ
# ==========================================

def get_pull_data_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Применить", callback_data="pull_data_yes")],
        [InlineKeyboardButton(text="Заполнить вручную", callback_data="pull_data_no")],
        [InlineKeyboardButton(text="Вернуться в начало", callback_data="acc_stock_back")]
    ])
    return kb

def get_create_without_claim_button():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Создать без заявки", callback_data="create_without_claim")],
        [InlineKeyboardButton(text="Вернуться в начало", callback_data="acc_stock_back")]
    ])
    return kb

# ==========================================
# КЛАВИАТУРЫ ДЛЯ TRADE-IN
# ==========================================

def get_tradein_sim_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Only eSim", callback_data="tradein_sim_esim")],
        [InlineKeyboardButton(text="Dual Sim", callback_data="tradein_sim_dual")],
        [InlineKeyboardButton(text="Sim+eSim", callback_data="tradein_sim_sim_esim")]
    ])
    return kb

def get_tradein_condition_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Как новый (без дефектов)", callback_data="tradein_cond_new")],
        [InlineKeyboardButton(text="Следы эксплуатации", callback_data="tradein_cond_used")],
        [InlineKeyboardButton(text="Разбитый", callback_data="tradein_cond_broken")]
    ])
    return kb

def get_tradein_screen_condition_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без дефектов", callback_data="tradein_screen_none")],
        [InlineKeyboardButton(text="Мелкие царапины", callback_data="tradein_screen_minor")],
        [InlineKeyboardButton(text="Глубокие царапины", callback_data="tradein_screen_deep")],
        [InlineKeyboardButton(text="Сколы", callback_data="tradein_screen_chips")]
    ])
    return kb

def get_tradein_body_condition_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без дефектов", callback_data="tradein_body_none")],
        [InlineKeyboardButton(text="Мелкие царапины", callback_data="tradein_body_minor")],
        [InlineKeyboardButton(text="Глубокие царапины", callback_data="tradein_body_deep")],
        [InlineKeyboardButton(text="Сколы", callback_data="tradein_body_chips")]
    ])
    return kb

def get_tradein_repair_choice_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без ремонтов", callback_data="tradein_repair_none")],
        [InlineKeyboardButton(text="Указать ремонты", callback_data="tradein_repair_specify")]
    ])
    return kb

def get_tradein_payment_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Наличные", callback_data="tradein_pay_cash")],
        [InlineKeyboardButton(text="Банковская карта", callback_data="tradein_pay_card")],
        [InlineKeyboardButton(text="Кредит/Рассрочка", callback_data="tradein_pay_credit")]
    ])
    return kb

def get_tradein_competitor_offer_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Не оценивали", callback_data="tradein_competitor_none")]
    ])
    return kb

def get_tradein_equipment_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Только техника", callback_data="tradein_equip_device_only")],
        [InlineKeyboardButton(text="Техника + коробка", callback_data="tradein_equip_box")],
        [InlineKeyboardButton(text="Техника + коробка + кабель", callback_data="tradein_equip_box_cable")],
        [InlineKeyboardButton(text="Техника + коробка + кабель + сзу", callback_data="tradein_equip_box_cable_charger")]
    ])
    return kb

def get_tradein_outcome_buttons(claim_id: int):
    """Кнопки решения ТТ по итогу сделки — показываются автору заявки ПОСЛЕ того,
    как администратор одобрил сумму выкупа (см. handlers/tradein.py).
    «Сделка состоялась» → запрос фактической суммы выкупа; затем финальное
    уведомление «Устройство принято». «Сделка не состоялась» — без суммы."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Сделка состоялась", callback_data=f"tradein_outcome_accepted_{claim_id}")],
        [InlineKeyboardButton(text="❌ Сделка не состоялась", callback_data=f"tradein_outcome_cancelled_{claim_id}")]
    ])
    return kb

# ==========================================
# КЛАВИАТУРЫ ДЛЯ ЧАТА ЗАЯВКИ (ОБСУЖДЕНИЕ)
# ==========================================

def get_chat_button(claim_id: int) -> InlineKeyboardMarkup:
    """Одна кнопка входа в чат заявки. Добавляется во все карточки заявки,
    которые видят участники чата (автор, ответственный админ, супер-админы)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Чат заявки", callback_data=f"chat_open_{claim_id}")]
    ])


def append_chat_button_row(kb: InlineKeyboardMarkup, claim_id: int) -> InlineKeyboardMarkup:
    """Добавляет строку с кнопкой чата в уже существующую inline-клавиатуру
    (например, к клавиатуре с кнопками решения администратора), не создавая
    для каждой карточки заявки отдельного сообщения."""
    kb.inline_keyboard.append(
        [InlineKeyboardButton(text="💬 Чат заявки", callback_data=f"chat_open_{claim_id}")]
    )
    return kb


def get_chat_history_keyboard(
    claim_id: int,
    is_locked: bool,
    can_reopen: bool,
    can_reply_last: bool,
    can_close: bool = False,
) -> InlineKeyboardMarkup:
    """Клавиатура под историей переписки заявки.

    is_locked — чат закрыт (заявка решена, либо закрыт вручную) и доступен только для чтения.
    can_reopen — может ли текущий пользователь повторно открыть чат (только супер-админ),
        актуально только когда is_locked=True.
    can_reply_last — есть ли в истории хотя бы одно сообщение, на которое можно ответить.
    can_close — может ли текущий пользователь закрыть обсуждение вручную (только супер-админ),
        актуально только когда is_locked=False — симметрично can_reopen.
    """
    rows = []
    if not is_locked:
        rows.append([InlineKeyboardButton(text="✍ Написать сообщение", callback_data=f"chat_write_{claim_id}")])
        rows.append([InlineKeyboardButton(text="📷 Фото", callback_data=f"chat_photo_{claim_id}")])
        if can_reply_last:
            rows.append([InlineKeyboardButton(text="↩️ Ответить на последнее", callback_data=f"chat_reply_last_{claim_id}")])
        if can_close:
            rows.append([InlineKeyboardButton(text="⛔ Закрыть обсуждение", callback_data=f"chat_close_{claim_id}")])
    elif can_reopen:
        rows.append([InlineKeyboardButton(text="🔓 Возобновить обсуждение", callback_data=f"chat_reopen_{claim_id}")])
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data=f"chat_back_{claim_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_chat_cancel_keyboard(claim_id: int) -> InlineKeyboardMarkup:
    """Клавиатура на время ожидания ввода сообщения/фото в чат — позволяет отменить ввод."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data=f"chat_cancel_{claim_id}")]
    ])
