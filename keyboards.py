from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

def get_main_menu():
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Техника"), KeyboardButton(text="🎧 Аксессуар")]
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
        [InlineKeyboardButton(text="Возврат", callback_data="wish_return"), InlineKeyboardButton(text="Обмен", callback_data="wish_exchange")]
    ])
    return kb

def get_admin_decision(claim_id: int):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"adm_approve_{claim_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_reject_{claim_id}")]
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

def get_role_selection_buttons():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠 Техника (admin_tech)", callback_data="role_tech")],
        [InlineKeyboardButton(text="🎧 Аксессуары (admin_acc)", callback_data="role_acc")],
        [InlineKeyboardButton(text="👑 Супер-админ (super_admin)", callback_data="role_super")]
    ])
    return kb

def get_stats_menu():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 Общая статистика", callback_data="stats_overview")],
        [InlineKeyboardButton(text="🏢 Подробно по ТТ", callback_data="stats_points")],
        [InlineKeyboardButton(text="⏳ Просроченные заявки", callback_data="stats_pending")],
        [InlineKeyboardButton(text="📥 Экспорт в CSV", callback_data="stats_export")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_admin")]
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
