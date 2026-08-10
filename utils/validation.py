from datetime import datetime

from utils.tz import today_local

FUTURE_PURCHASE_DATE_TEXT = "Нельзя указать дату покупки в будущем. Укажите корректную дату."


def is_valid_date_ddmmyyyy(value: str) -> bool:
    text = (value or "").strip()
    if len(text) != 10:
        return False
    try:
        datetime.strptime(text, "%d.%m.%Y")
        return True
    except ValueError:
        return False


def is_future_date_ddmmyyyy(value: str) -> bool:
    """True, если строка — валидная дата ДД.ММ.ГГГГ, строго ПОЗЖЕ сегодняшнего
    дня в часовом поясе Asia/Yekaterinburg (см. utils.tz.today_local — не
    date.today(), чтобы не ошибиться на пару часов около полуночи из-за
    часового пояса сервера).

    Формат ожидается уже проверенным ОТДЕЛЬНО через is_valid_date_ddmmyyyy —
    для невалидного формата возвращает False (не "в будущем", а "не дата
    вовсе"), чтобы вызывающий код показывал именно свою ошибку формата.
    """
    text = (value or "").strip()
    if len(text) != 10:
        return False
    try:
        parsed = datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        return False
    return parsed > today_local()


def parse_money(value: str, allow_negative: bool = False) -> float | None:
    text = (value or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not allow_negative and number < 0:
        return None
    return number


def format_money_rub(amount: float) -> str:
    """Форматирует сумму для показа пользователю: "50 000 ₽" (разряды через
    пробел, без ".0" для целых сумм)."""
    if amount == int(amount):
        formatted = f"{int(amount):,}".replace(",", " ")
    else:
        formatted = f"{amount:,.2f}".replace(",", " ")
    return f"{formatted} ₽"
