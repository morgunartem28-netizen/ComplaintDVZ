from datetime import datetime


def is_valid_date_ddmmyyyy(value: str) -> bool:
    text = (value or "").strip()
    if len(text) != 10:
        return False
    try:
        datetime.strptime(text, "%d.%m.%Y")
        return True
    except ValueError:
        return False


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
