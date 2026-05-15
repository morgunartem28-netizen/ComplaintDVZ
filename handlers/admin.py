from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from database import (
    get_user_role, update_claim_status, get_claim, log_action, 
    set_user_role, add_claim_history, get_admins_by_role,
    try_update_claim_status,
)
from keyboards import (
    get_admin_panel_menu, get_role_selection_buttons, get_main_menu,
    get_stock_adjustment_request_buttons,
)
from utils.admin_panel import (
    ACCESS_DENIED,
    ACCESS_DENIED_SHORT,
    is_super_admin,
    send_panel,
    show_panel,
)
from bot_instance import bot
from states import AdminActionFSM, SuperAdminFSM
import logging
from utils.markdown import escape_markdown

router = Router()
logger = logging.getLogger(__name__)

# ==========================================
# ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ПРОВЕРКИ ДОСТУПА
# ==========================================
async def check_admin_access(admin_id: int, claim_category: str) -> bool:
    role = await get_user_role(admin_id)
    if role == 'super_admin':
        return True
    if role == 'admin_tech' and claim_category == 'tech':
        return True
    if role == 'admin_acc' and claim_category == 'acc':
        return True
    if role == 'admin_tradein' and claim_category == 'tradein':
        return True
    return False

# ==========================================
# ОДОБРЕНИЕ ЗАЯВКИ (для аксессуаров)
# ==========================================
@router.callback_query(F.data.startswith("adm_approve_"))
async def admin_approve(cb: CallbackQuery, state: FSMContext):
    try:
        claim_id = int(cb.data.split("_")[-1])
        full_name = cb.from_user.full_name or "Админ"
        claim = await get_claim(claim_id)
        
        if not claim:
            await cb.answer("Заявка не найдена", show_alert=True)
            return

        if not await check_admin_access(cb.from_user.id, claim['category']):
            await cb.answer("⛔ У вас нет прав для обработки этой заявки", show_alert=True)
            return

        # === АТОМАРНАЯ ПРОВЕРКА: заявка ещё не обработана? ===
        success, updated_claim = await try_update_claim_status(
            claim_id, 'approved', admin_name=full_name
        )
        
        if success is None:
            await cb.answer("Заявка не найдена", show_alert=True)
            return
            
        if not success:
            # Заявка уже обработана другим админом
            current_status = updated_claim.get('status', 'unknown')
            current_admin = updated_claim.get('admin_name', 'другой администратор')
            await cb.answer(
                f"⚠️ Заявка уже обработана ({current_status}).\n"
                f"Решение принял: {current_admin}",
                show_alert=True
            )
            return

        # Успешно обновлено — продолжаем стандартный flow
        old_status = claim.get('status', "pending")
        display_id = claim.get('display_id', f'#{claim_id}')

        await add_claim_history(claim_id, display_id, old_status, 'approved', cb.from_user.id, full_name)
        await log_action(cb.from_user.id, 'approve', claim_id)

        safe_admin_name = escape_markdown(full_name)
        new_caption = f"{cb.message.caption}\n\n✅ **ОДОБРЕНО** (Админ: {safe_admin_name})"
        await cb.message.edit_caption(caption=new_caption, parse_mode="Markdown")

        user_id = claim.get('user_id')
        try:
            await bot.send_message(
                user_id, 
                f"✅ Ваша заявка **{display_id}** одобрена!\n"
                f"Решение принял: {safe_admin_name}\n\n"
                f"⚠️ Если возвращённый товар непригоден для продажи "
                f"(не работает, сломан, разбит и т.д.), его необходимо отбраковать и приложить номер заявки к накладной."
            )
        except Exception as e:
            logger.warning("Failed to notify user on approve: %s", e)

        if claim['category'] == 'acc':
            try:
                await bot.send_message(
                    user_id, 
                    f"📋 **Рекомендация по заявке {display_id}**\n\n"
                    f"Если необходимо скорректировать остатки товара, отправьте запрос Факиевой Эльвире", 
                    reply_markup=get_stock_adjustment_request_buttons(claim_id), 
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.warning("Failed to send stock adjustment suggestion: %s", e)

    except Exception as e:
        logger.error("Error during admin approve: %s", e)
        await cb.answer("Произошла ошибка при обработке.")

# ==========================================
# ОТКЛОНЕНИЕ ЗАЯВКИ
# ==========================================
@router.callback_query(F.data.startswith("adm_reject_"))
async def admin_reject_start(cb: CallbackQuery, state: FSMContext):
    claim_id = int(cb.data.split("_")[-1])
    claim = await get_claim(claim_id)
    
    if not claim:
        await cb.answer("Заявка не найдена", show_alert=True)
        return

    if not await check_admin_access(cb.from_user.id, claim['category']):
        await cb.answer("⛔ У вас нет прав для обработки этой заявки", show_alert=True)
        return

    # === ПРОВЕРКА: заявка ещё не обработана? ===
    if claim.get('status') != 'pending':
        current_status = claim.get('status', 'unknown')
        current_admin = claim.get('admin_name', 'другой администратор')
        await cb.answer(
            f"⚠️ Заявка уже обработана ({current_status}).\n"
            f"Решение принял: {current_admin}",
            show_alert=True
        )
        return

    await state.update_data(reject_claim_id=claim_id, claim_category=claim['category'])
    await cb.message.answer("📝 Введите причину отказа:")
    await state.set_state(AdminActionFSM.reject_comment)

@router.message(AdminActionFSM.reject_comment)
async def admin_reject_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    claim_id = data.get('reject_claim_id')
    
    if not claim_id:
        await message.answer("❌ Ошибка: ID заявки не найден.")
        await state.clear()
        return

    claim = await get_claim(claim_id)
    if claim and not await check_admin_access(message.from_user.id, claim['category']):
        await message.answer("⛔ У вас нет прав для обработки этой заявки.")
        await state.clear()
        return

    # === АТОМАРНАЯ ПРОВЕРКА перед финальным отклонением ===
    full_name = message.from_user.full_name or "Админ"
    success, updated_claim = await try_update_claim_status(
        claim_id, 'rejected', comment=message.text, admin_name=full_name
    )
    
    if success is None:
        await message.answer("❌ Заявка не найдена.")
        await state.clear()
        return
        
    if not success:
        current_status = updated_claim.get('status', 'unknown')
        current_admin = updated_claim.get('admin_name', 'другой администратор')
        await message.answer(
            f"⚠️ Заявка уже была обработана другим администратором ({current_status}).\n"
            f"Решение принял: {current_admin}"
        )
        await state.clear()
        return

    old_status = claim.get('status', "pending") if claim else "pending"
    display_id = claim.get('display_id', f'#{claim_id}') if claim else f'#{claim_id}'

    await add_claim_history(claim_id, display_id, old_status, 'rejected', message.from_user.id, full_name, message.text)
    await log_action(message.from_user.id, 'reject', claim_id)
    
    await state.clear()
    await message.answer("✅ Заявка отклонена, сотрудник уведомлен.")

    if claim:
        user_id = claim.get('user_id')
        try:
            await bot.send_message(
                user_id, 
                f"❌ Заявка **{display_id}** отклонена.\nПричина: {escape_markdown(message.text)}\nРешение принял: {escape_markdown(full_name)}"
            )
        except Exception as e:
            logger.warning("Failed to notify user on reject: %s", e)

# ==========================================
# ПТВ — ВОЗВРАТ/ОБМЕН
# ==========================================
@router.callback_query(F.data.startswith("adm_ptv_return_"))
async def admin_ptv_return(cb: CallbackQuery):
    try:
        claim_id = int(cb.data.split("_")[-1])
        full_name = cb.from_user.full_name or "Админ"
        claim = await get_claim(claim_id)
        
        if not claim:
            await cb.answer("Заявка не найдена", show_alert=True)
            return

        if not await check_admin_access(cb.from_user.id, claim['category']):
            await cb.answer("⛔ У вас нет прав для обработки этой заявки", show_alert=True)
            return

        # === АТОМАРНАЯ ПРОВЕРКА ===
        success, updated_claim = await try_update_claim_status(
            claim_id, 'approved', comment="Возврат/Обмен разрешен", admin_name=full_name
        )
        
        if success is None:
            await cb.answer("Заявка не найдена", show_alert=True)
            return
            
        if not success:
            current_status = updated_claim.get('status', 'unknown')
            current_admin = updated_claim.get('admin_name', 'другой администратор')
            await cb.answer(
                f"⚠️ Заявка уже обработана ({current_status}).\n"
                f"Решение принял: {current_admin}",
                show_alert=True
            )
            return

        old_status = claim.get('status', "pending")
        display_id = claim.get('display_id', f'#{claim_id}')

        await add_claim_history(claim_id, display_id, old_status, 'approved', cb.from_user.id, full_name, "Возврат/Обмен разрешен")
        await log_action(cb.from_user.id, 'ptv_return', claim_id)

        current_text = cb.message.text or "Выберите решение по заявке:"
        safe_admin_name = escape_markdown(full_name)
        new_text = (
            f"{current_text}\n\n"
            f"✅ **РЕШЕНИЕ ПРИНЯТО:**\n"
            f"Разрешен **ОБМЕН**.\n"
            f"(В случае отказа клиента — **ВОЗВРАТ**)\n\n"
            f"Решение принял: {safe_admin_name}"
        )
        await cb.message.edit_text(text=new_text, parse_mode="Markdown", reply_markup=None)

        user_id = claim.get('user_id')
        try:
            await bot.send_message(
                user_id, 
                f"✅ **Решение по заявке {display_id}:**\n\n"
                f"Разрешен **ОБМЕН**.\n"
                f"В случае отказа клиента от обмена, разрешен **ВОЗВРАТ**.\n\n"
                f"Решение принял: {safe_admin_name}"
            )
        except Exception as e:
            logger.warning("Failed to notify user on PTV return decision: %s", e)

        await cb.answer("Решение принято: Возврат/Обмен")
    except Exception as e:
        logger.error("Error in admin_ptv_return: %s", e)
        await cb.answer("Ошибка обработки")

# ==========================================
# ПТВ — ГАРАНТИЙНОЕ ОБСЛУЖИВАНИЕ
# ==========================================
@router.callback_query(F.data.startswith("adm_ptv_repair_"))
async def admin_ptv_repair(cb: CallbackQuery):
    try:
        claim_id = int(cb.data.split("_")[-1])
        full_name = cb.from_user.full_name or "Админ"
        claim = await get_claim(claim_id)
        
        if not claim:
            await cb.answer("Заявка не найдена", show_alert=True)
            return

        if not await check_admin_access(cb.from_user.id, claim['category']):
            await cb.answer("⛔ У вас нет прав для обработки этой заявки", show_alert=True)
            return

        # === АТОМАРНАЯ ПРОВЕРКА ===
        success, updated_claim = await try_update_claim_status(
            claim_id, 'approved', comment="Гарантийное обслуживание", admin_name=full_name
        )
        
        if success is None:
            await cb.answer("Заявка не найдена", show_alert=True)
            return
            
        if not success:
            current_status = updated_claim.get('status', 'unknown')
            current_admin = updated_claim.get('admin_name', 'другой администратор')
            await cb.answer(
                f"⚠️ Заявка уже обработана ({current_status}).\n"
                f"Решение принял: {current_admin}",
                show_alert=True
            )
            return

        old_status = claim.get('status', "pending")
        display_id = claim.get('display_id', f'#{claim_id}')

        await add_claim_history(claim_id, display_id, old_status, 'approved', cb.from_user.id, full_name, "Гарантийное обслуживание")
        await log_action(cb.from_user.id, 'ptv_repair', claim_id)

        current_text = cb.message.text or "Выберите решение по заявке:"
        safe_admin_name = escape_markdown(full_name)
        new_text = (
            f"{current_text}\n\n"
            f"✅ **РЕШЕНИЕ ПРИНЯТО:**\n"
            f"Технику необходимо принять на **Гарантийное обслуживание**.\n\n"
            f"Решение принял: {safe_admin_name}"
        )
        await cb.message.edit_text(text=new_text, parse_mode="Markdown", reply_markup=None)

        user_id = claim.get('user_id')
        try:
            await bot.send_message(
                user_id, 
                f"✅ **Решение по заявке {display_id}:**\n\n"
                f"Технику необходимо принять на **Гарантийное обслуживание**.\n\n"
                f"Решение принял: {safe_admin_name}"
            )
        except Exception as e:
            logger.warning("Failed to notify user on PTV repair decision: %s", e)

        await cb.answer("Решение принято: Гарантийное обслуживание")
    except Exception as e:
        logger.error("Error in admin_ptv_repair: %s", e)
        await cb.answer("Ошибка обработки")

# ==========================================
# ПАНЕЛЬ АДМИНИСТРАТОРА
# ==========================================
@router.message(F.text.in_({"/admin_panel", "/panel"}))
async def admin_panel(message: Message):
    if not await is_super_admin(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    await send_panel(message)


@router.callback_query(F.data == "panel_home")
async def panel_home(cb: CallbackQuery):
    if not await is_super_admin(cb.from_user.id):
        await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
        return
    await show_panel(cb)


@router.callback_query(F.data == "panel_refresh")
async def panel_refresh(cb: CallbackQuery):
    if not await is_super_admin(cb.from_user.id):
        await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
        return
    await show_panel(cb, toast="Обновлено")

# ==========================================
# УПРАВЛЕНИЕ АДМИНАМИ
# ==========================================
@router.callback_query(F.data == "sa_add_admin_menu")
async def sa_add_menu(cb: CallbackQuery, state: FSMContext):
    if not await is_super_admin(cb.from_user.id):
        await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
        return
    
    await state.clear()
    await cb.message.edit_text(
        "👮 **Назначение админа**\n\n"
        "1. Введите ID пользователя в чат.\n"
        "2. Выберите роль кнопками ниже.",
        reply_markup=get_role_selection_buttons(),
        parse_mode="Markdown"
    )
    await state.set_state(SuperAdminFSM.waiting_for_id)

@router.message(SuperAdminFSM.waiting_for_id)
async def sa_receive_id(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ ID должен быть числом. Попробуйте снова.")
        return
    
    await state.update_data(target_id=int(text))
    await message.answer("✅ ID принят. Выберите роль:", reply_markup=get_role_selection_buttons())

@router.callback_query(F.data.startswith("role_"))
async def sa_assign_role(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    target_id = data.get('target_id')
    
    if not target_id:
        await cb.answer("Ошибка: ID не найден. Начните заново.", show_alert=True)
        await state.clear()
        return

    role_map = {
        "role_tech": "admin_tech",
        "role_acc": "admin_acc",
        "role_tradein": "admin_tradein",
        "role_complaint": "admin_complaint",
        "role_super": "super_admin"
    }
    
    new_role = role_map.get(cb.data)
    if not new_role:
        await cb.answer("Ошибка роли.", show_alert=True)
        return

    try:
        await set_user_role(target_id, new_role)
        await log_action(cb.from_user.id, 'assign_role', target_id)
        
        role_names = {
            "admin_tech": "Техника",
            "admin_acc": "Аксессуары",
            "admin_tradein": "Trade-in",
            "admin_complaint": "Остатки",
            "super_admin": "Супер-админ"
        }
        
        await cb.message.edit_text(
            f"✅ **Админ назначен!**\n\n"
            f"🆔 ID: `{target_id}`\n"
            f"🛡 Роль: **{role_names[new_role]}**",
            reply_markup=get_admin_panel_menu(),
            parse_mode="Markdown"
        )
        await state.clear()
        
        try:
            await bot.send_message(
                target_id, 
                f"🎉 Вы назначены администратором ({role_names[new_role]}) в боте."
            )
        except Exception as e:
            logger.warning("Failed to notify new admin: %s", e)
            
    except Exception as e:
        await cb.answer(f"Ошибка: {e}", show_alert=True)

@router.callback_query(F.data == "sa_del_admin_menu")
async def sa_del_menu(cb: CallbackQuery, state: FSMContext):
    if not await is_super_admin(cb.from_user.id):
        await cb.answer(ACCESS_DENIED_SHORT, show_alert=True)
        return
    
    await state.clear()
    await cb.message.edit_text(
        "🗑 **Снятие прав**\n\nВведите ID пользователя, которого нужно лишить прав.",
        parse_mode="Markdown",
    )
    await state.set_state(SuperAdminFSM.waiting_for_id_delete)

@router.message(SuperAdminFSM.waiting_for_id_delete)
async def sa_del_admin_finish(message: Message, state: FSMContext):
    await state.clear()
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ ID должен быть числом.")
        return
    
    uid = int(text)
    current_role = await get_user_role(uid)
    
    if current_role == 'user':
        await message.answer(f"ℹ️ Пользователь {uid} уже не является администратором.")
        return

    await set_user_role(uid, 'user')
    await log_action(message.from_user.id, 'del_admin', uid)
    
    await message.answer(
        f"✅ Пользователь {uid} лишен прав.",
        reply_markup=get_admin_panel_menu()
    )
    
    try:
        await bot.send_message(uid, "⚠️ Ваши права администратора сняты.")
    except Exception as e:
        logger.warning("Failed to notify user about role removal: %s", e)
