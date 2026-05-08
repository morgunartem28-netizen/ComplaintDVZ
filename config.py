import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
def _parse_admin_ids(raw: str) -> list[int]:
    result = []
    for chunk in (raw or "").split(","):
        value = chunk.strip()
        if not value:
            continue
        try:
            result.append(int(value))
        except ValueError:
            continue
    return result

ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))
DB_NAME = os.getenv("DB_NAME", "claims.db")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "1713290400"))
