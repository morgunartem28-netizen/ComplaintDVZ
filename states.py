from aiogram.fsm.state import State, StatesGroup

class AccState(StatesGroup):
    client_name = State()
    nomenclature = State()
    date = State()
    photo = State()
    defect = State()
    wish = State()

class TechState(StatesGroup):
    type_choice = State()
    # ПТВ
    ptv_device_name = State()
    ptv_imei = State()
    ptv_defect = State()
    ptv_mp_check = State()
    ptv_date = State()
    ptv_client_name = State()
    ptv_photo_front = State()
    ptv_photo_back = State()
    ptv_warranty_choice = State()
    ptv_photo_warranty = State()
    # Новое устройство
    new_device_name = State()
    new_imei = State()
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

class TradeinState(StatesGroup):
    model = State()
    sim = State()
    memory = State()
    condition = State()
    battery = State()
    repair = State()
    equipment = State()
    activation_date = State()
    target_model = State()
    photos = State()

class TradeinAdminFSM(StatesGroup):
    waiting_for_price = State()

# ==========================================
# СОСТОЯНИЯ ДЛЯ COMPLAINT (ВОЗВРАТ/ОБМЕН АКСЕССУАРОВ)
# ==========================================

class ComplaintFSM(StatesGroup):
    waiting_price = State()
    waiting_refund_method = State()
    waiting_refund_date = State()

class ExchangeFSM(StatesGroup):
    waiting_returned_price = State()
    waiting_new_item = State()
    waiting_new_price = State()
    waiting_diff_method = State()
    waiting_exchange_date = State()
    waiting_receipt_voided = State()

# ==========================================
# СОСТОЯНИЯ ДЛЯ КОРРЕКТИРОВКИ ТЕХНИКИ
# ==========================================

class TechAdjustmentFSM(StatesGroup):
    # Выбор: подтянуть из заявки или создать новую
    waiting_tech_claim_number = State()
    confirm_pull_data = State()
    # Возврат техники
    return_nomenclature = State()
    return_imei = State()
    return_price = State()
    return_purchase_date = State()
    return_refund_method = State()
    return_refund_date = State()
    return_location = State()
    return_receipt_voided = State()
    return_approver = State()
    # Обмен техники
    exchange_nomenclature = State()
    exchange_imei = State()
    exchange_price = State()
    exchange_purchase_date = State()
    exchange_new_nomenclature = State()
    exchange_new_imei = State()
    exchange_new_price = State()
    exchange_diff_method = State()
    exchange_date = State()
    exchange_location = State()
    exchange_receipt_voided = State()
    exchange_approver = State()
