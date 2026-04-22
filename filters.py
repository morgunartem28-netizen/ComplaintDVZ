from aiogram import BaseFilter
from aiogram.types import Message, CallbackQuery
from database import get_user_role

class IsSuperAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user_id = event.from_user.id
        role = await get_user_role(user_id)
        return role == 'super_admin'

class IsTechAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user_id = event.from_user.id
        role = await get_user_role(user_id)
        return role in ['super_admin', 'admin_tech']

class IsAccAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user_id = event.from_user.id
        role = await get_user_role(user_id)
        return role in ['super_admin', 'admin_acc']
