import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))
DB_NAME = os.getenv("DB_NAME", "claims.db")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", "1713290400"))
