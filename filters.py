from aiogram.filters import BaseFilter
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

class IsTradeinAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user_id = event.from_user.id
        role = await get_user_role(user_id)
        return role in ['super_admin', 'admin_tradein']

class IsComplaintAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user_id = event.from_user.id
        role = await get_user_role(user_id)
        return role in ['super_admin', 'admin_complaint']


class MainMenuButton(BaseFilter):
    """Сравнивает текст сообщения с настраиваемой подписью главной кнопки.

    key: tech | acc | tradein | stock_adjustment
    """

    def __init__(self, key: str):
        self.key = key

    async def __call__(self, message: Message) -> bool:
        if not message.text:
            return False
        from utils.bot_config import get_setting
        setting_key = {
            "tech": "button.main.tech",
            "acc": "button.main.acc",
            "tradein": "button.main.tradein",
            "stock_adjustment": "button.main.stock_adjustment_label",
        }.get(self.key)
        if not setting_key:
            return False
        if self.key == "stock_adjustment":
            if (await get_setting("button.main.stock_adjustment", "0")) != "1":
                return False
        label = await get_setting(setting_key)
        return message.text == label
