_MARKDOWN_SPECIAL_CHARS = ("_", "*", "`", "[", "]", "(", ")")


def escape_markdown(text) -> str:
    """Экранирует текст для безопасной отправки с parse_mode="Markdown" (legacy).

    Единая точка экранирования для всего пользовательского ввода, вставляемого
    в сообщения бота. Экранирует все спецсимволы, которые могут привести к
    ошибке Telegram "can't parse entities" и, как следствие, к недоставке
    сообщения (например, уведомления администратору о новой заявке).
    """
    if text is None:
        return ""
    escaped = str(text).replace("\\", "\\\\")
    for ch in _MARKDOWN_SPECIAL_CHARS:
        escaped = escaped.replace(ch, f"\\{ch}")
    return escaped
