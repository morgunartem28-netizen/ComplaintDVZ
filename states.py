# states.py
from aiogram.fsm.state import State, StatesGroup

class AccState(StatesGroup):
    # Убрали type_choice, теперь сразу переходим к данным
    client_name = State()
    nomenclature = State()
    date = State()
    photo = State()
    defect = State()
    wish = State()

class TechState(StatesGroup):
    type_choice = State()
    ptv_defect = State()
    ptv_mp_check = State()
    ptv_date = State()
    ptv_client_name = State()
    ptv_photo_front = State()
    ptv_photo_back = State()
    ptv_warranty_choice = State()
    ptv_photo_warranty = State()
    new_device_name = State()
    new_defect = State()
    new_date = State()
    new_client_name = State()
    new_photo_front = State()
    new_photo_back = State()
    new_warranty_choice = State()
    new_photo_warranty = State()

class AdminActionFSM(StatesGroup):
    reject_comment = State()

class SuperAdminFSM(StatesGroup):
    waiting_for_id = State()
    waiting_for_id_delete = State()
