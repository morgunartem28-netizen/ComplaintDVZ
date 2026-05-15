from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

def get_main_menu():
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Техника"), KeyboardButton(text="Аксессуар")],
            [KeyboardButton(text="Trade-in"), KeyboardButton(text="Запрос на корректировку остатков")]
        ],
        resize_keyboard=True
    )
    return kb

def get_cancel_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

def get_acc_types():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Стекло", callback_data="acc_glass"), InlineKeyboardButton(text="СЗУ", callback_data="acc_charger")],
        [InlineKeyboardButton(text="Кабель", callback_data="acc_cable"), InlineKeyboardButton(text="Другое", callback_data="acc_other")]
    ])
    return kb

def get_tech_type_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠 Б/У", callback_data="tech_ptv")],
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

def get_admin_panel_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="panel_refresh")],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="sa_stats_menu"),
            InlineKeyboardButton(text="📥 Excel", callback_data="stats_export_menu_panel"),
        ],
        [
            InlineKeyboardButton(text="👮 Назначить", callback_data="sa_add_admin_menu"),
            InlineKeyboardButton(text="🗑 Снять права", callback_data="sa_del_admin_menu"),
        ],
        [InlineKeyboardButton(text="📋 Список админов", callback_data="sa_list_admins")],
        [InlineKeyboardButton(text="🧹 Очистить БД", callback_data="sa_clear_db")],
    ])
    return kb


def get_super_admin_menu():
    return get_admin_panel_menu()

def get_role_selection_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠 Техника", callback_data="role_tech")],
        [InlineKeyboardButton(text="🎧 Аксессуары", callback_data="role_acc")],
        [InlineKeyboardButton(text="🔄 Trade-in", callback_data="role_tradein")],
        [InlineKeyboardButton(text="📦 Остатки", callback_data="role_complaint")],
        [InlineKeyboardButton(text="👑 Супер-админ", callback_data="role_super")],
        [InlineKeyboardButton(text="⬅️ На главную", callback_data="panel_home")],
    ])
    return kb

def get_stats_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Общая статистика", callback_data="stats_overview")],
        [InlineKeyboardButton(text="🏢 Подробно по ТТ", callback_data="stats_points")],
        [InlineKeyboardButton(text="⏳ Просроченные заявки", callback_data="stats_pending")],
        [InlineKeyboardButton(text="📥 Экспорт Excel", callback_data="stats_export_menu")],
        [InlineKeyboardButton(text="⬅️ На главную", callback_data="panel_home")]
    ])
    return kb


def get_export_period_buttons(back_callback: str = "panel_home"):
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
        [InlineKeyboardButton(text="⬅️ На главную", callback_data="panel_home")]
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
