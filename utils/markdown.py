def escape_markdown(text: str) -> str:
    if text is None:
        return ""
    escaped = str(text).replace("\\", "\\\\")
    for ch in ("_", "*", "`", "["):
        escaped = escaped.replace(ch, f"\\{ch}")
    return escaped
