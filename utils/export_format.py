import re
from datetime import datetime

STATUS_RU = {
    "pending": "Ожидает",
    "approved": "Одобрено",
    "rejected": "Отклонено",
    "repair": "Ремонт",
    "quality_check": "Проверка качества",
    "expired": "Срок истёк",
    "error_date": "Ошибка даты",
}

CATEGORY_RU = {
    "tech": "Техника",
    "acc": "Аксессуары",
    "tradein": "Trade-in",
    "complaint": "Остатки",
}


def format_status_ru(status: str | None) -> str:
    if not status:
        return ""
    return STATUS_RU.get(status, status)


def format_category_ru(category: str | None) -> str:
    if not category:
        return ""
    return CATEGORY_RU.get(category, category)


def extract_product_name(brand: str | None, category: str | None) -> str:
    brand = (brand or "").strip()
    if not brand or brand == "N/A":
        return ""
    if category == "tech" and "| IMEI:" in brand:
        return brand.split("| IMEI:", 1)[0].strip()
    return brand


def extract_imei(brand: str | None, defect_desc: str | None, category: str | None) -> str:
    brand = brand or ""
    defect = (defect_desc or "").strip()

    if category == "tech" and "| IMEI:" in brand:
        return brand.split("| IMEI:", 1)[1].strip()

    if defect.upper().startswith("IMEI:"):
        return defect.split(":", 1)[1].strip()

    match = re.search(r"IMEI:\s*([^\s|]+)", defect, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()

    match = re.search(r"IMEI:\s*([^\s|]+)", brand, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()

    return ""


def format_defect_for_export(
    defect_desc: str | None,
    category: str | None,
    brand: str | None,
) -> str:
    defect = (defect_desc or "").strip()
    if not defect:
        return ""

    if category == "tradein":
        return ""

    if category == "complaint" and defect.upper().startswith("IMEI:"):
        return ""

    if category == "tech" and defect.upper().startswith("IMEI:"):
        return ""

    return defect


EXPORT_DATETIME_FMT = "%d.%m.%Y %H:%M"

_PARSE_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
)


def format_datetime_export(value) -> str:
    """Единый формат для Excel: ДД.ММ.ГГГГ ЧЧ:ММ (без секунд)."""
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    for fmt in _PARSE_DATETIME_FORMATS:
        try:
            dt = datetime.strptime(text[:26], fmt)
            return dt.strftime(EXPORT_DATETIME_FMT)
        except ValueError:
            continue

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime(EXPORT_DATETIME_FMT)
    except ValueError:
        pass

    if " " in text:
        date_part, time_part = text.split(" ", 1)
        time_short = time_part.split(".")[0][:5]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_part):
            try:
                dt = datetime.strptime(f"{date_part} {time_short}", "%Y-%m-%d %H:%M")
                return dt.strftime(EXPORT_DATETIME_FMT)
            except ValueError:
                pass
        return f"{date_part} {time_short}".strip()

    return text


def split_datetime_export(value) -> tuple[str, str]:
    """Дата и время отдельно: ДД.ММ.ГГГГ и ЧЧ:ММ."""
    full = format_datetime_export(value)
    if not full or " " not in full:
        return full, ""
    date_part, time_part = full.split(" ", 1)
    return date_part, time_part
