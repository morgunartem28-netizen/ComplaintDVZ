import aiosqlite
import csv
import io
from datetime import datetime
from config import DB_NAME, ADMIN_IDS

# ID супер-админов из .env (список)
ENV_SUPER_ADMIN_IDS = ADMIN_IDS if ADMIN_IDS else []

async def archive_old_claims(days: int = 365):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(f"""
            INSERT INTO claims_archive SELECT * FROM claims 
            WHERE date(created_at) < date('now', '-{days} days')
        """)
        await db.execute(f"""
            DELETE FROM claims 
            WHERE date(created_at) < date('now', '-{days} days')
        """)
        await db.commit()
        cursor = await db.execute("SELECT changes()")
        archived_count = (await cursor.fetchone())[0]
        return archived_count

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                role TEXT DEFAULT 'user'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                category TEXT,
                sub_category TEXT,
                brand TEXT,
                defect_desc TEXT,
                purchase_date TEXT,
                client_wish TEXT,
                photo_id TEXT,
                status TEXT DEFAULT 'pending',
                admin_comment TEXT,
                admin_name TEXT,
                client_name TEXT DEFAULT 'Не указано',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                target_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS updates_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                update_type TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS claim_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id INTEGER,
                old_status TEXT,
                new_status TEXT,
                admin_id INTEGER,
                admin_name TEXT,
                comment TEXT,
                changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS claims_archive AS SELECT * FROM claims WHERE 1=0
        """)
        
        # Авто-назначение супер-админов из .env
        if ENV_SUPER_ADMIN_IDS:
            for admin_id in ENV_SUPER_ADMIN_IDS:
                await db.execute(
                    "INSERT OR REPLACE INTO users (user_id, role) VALUES (?, ?)",
                    (admin_id, 'super_admin')
                )
        
        await db.commit()

async def get_user_role(user_id: int) -> str:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
        res = await cursor.fetchone()
        return res[0] if res else 'user'

async def set_user_role(user_id: int, role: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT OR REPLACE INTO users (user_id, role) VALUES (?, ?)",
            (user_id, role)
        )
        await db.commit()

async def log_action(admin_id: int, action: str, target_id: int = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO logs (admin_id, action, target_id) VALUES (?, ?, ?)",
            (admin_id, action, target_id)
        )
        await db.commit()

async def log_update(user_id: int, update_type: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO updates_log (user_id, update_type) VALUES (?, ?)",
            (user_id, update_type)
        )
        await db.commit()

async def create_claim(data: dict, user_id: int) -> int:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            INSERT INTO claims (user_id, category, sub_category, brand, defect_desc, purchase_date, client_wish, photo_id, client_name) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, 
            data['category'], 
            data['sub_category'], 
            data.get('brand'), 
            data['defect'], 
            data.get('date'), 
            data.get('wish'), 
            data['photo'], 
            data.get('client_name', 'Не указано')
        ))
        await db.commit()
        return cursor.lastrowid

async def get_claim(claim_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row 
        cursor = await db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return dict(row)

async def update_claim_status(claim_id: int, status: str, comment: str = None, admin_name: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE claims SET status = ?, admin_comment = ?, admin_name = ? WHERE id = ?",
            (status, comment, admin_name, claim_id)
        )
        await db.commit()

async def add_claim_history(claim_id: int, old_status: str, new_status: str, 
                            admin_id: int, admin_name: str, comment: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO claim_history (claim_id, old_status, new_status, admin_id, admin_name, comment) 
            VALUES (?, ?, ?, ?, ?, ?)
        """, (claim_id, old_status, new_status, admin_id, admin_name, comment))
        await db.commit()

async def get_claim_history(claim_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT old_status, new_status, admin_name, comment, changed_at 
            FROM claim_history WHERE claim_id = ? ORDER BY changed_at DESC
        """, (claim_id,))
        return await cursor.fetchall()

async def get_admins_by_role(role_prefix: str):
    async with aiosqlite.connect(DB_NAME) as db:
        if role_prefix == 'super_admin':
            # Только супер-админы из БД + гарантированно из .env
            cursor = await db.execute("SELECT user_id FROM users WHERE role = 'super_admin'")
            rows = await cursor.fetchall()
            db_admins = [row[0] for row in rows]
            return list(set(db_admins + ENV_SUPER_ADMIN_IDS))
        
        elif role_prefix in ('admin_tech', 'admin_acc'):
            # Специфичные админы + супер-админы из БД + гарантированно из .env
            cursor = await db.execute(
                "SELECT user_id FROM users WHERE role = ? OR role = 'super_admin'",
                (role_prefix,)
            )
            rows = await cursor.fetchall()
            db_admins = [row[0] for row in rows]
            return list(set(db_admins + ENV_SUPER_ADMIN_IDS))
        
        else:
            cursor = await db.execute("SELECT user_id FROM users WHERE role = ?", (role_prefix,))
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

async def get_stats_overview():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor_total = await db.execute("SELECT COUNT(*) FROM claims")
        total = (await cursor_total.fetchone())[0]
        cursor_pending = await db.execute("SELECT COUNT(*) FROM claims WHERE status = 'pending'")
        pending = (await cursor_pending.fetchone())[0]
        cursor_resolved = await db.execute(
            "SELECT COUNT(*) FROM claims WHERE status IN ('approved', 'rejected', 'repair', 'quality_check')"
        )
        resolved = (await cursor_resolved.fetchone())[0]
        return {'total': total, 'pending': pending, 'resolved': resolved}

async def get_stats_by_points():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT DISTINCT user_id FROM claims")
        user_ids = [row[0] for row in await cursor.fetchall()]
        stats_list = []
        for uid in user_ids:
            cursor_ptv = await db.execute(
                "SELECT COUNT(*) FROM claims WHERE user_id = ? AND sub_category = 'ПТВ'",
                (uid,)
            )
            ptv = (await cursor_ptv.fetchone())[0]
            cursor_new = await db.execute(
                "SELECT COUNT(*) FROM claims WHERE user_id = ? AND sub_category = 'Новое устройство'",
                (uid,)
            )
            new_dev = (await cursor_new.fetchone())[0]
            cursor_acc = await db.execute(
                "SELECT COUNT(*) FROM claims WHERE user_id = ? AND category = 'acc'",
                (uid,)
            )
            acc = (await cursor_acc.fetchone())[0]
            total = ptv + new_dev + acc
            if total > 0:
                stats_list.append({
                    'user_id': uid,
                    'name': f"ТТ #{uid}",
                    'ptv': ptv,
                    'new': new_dev,
                    'acc': acc,
                    'total': total
                })
        stats_list.sort(key=lambda x: x['total'], reverse=True)
        return stats_list

async def get_pending_claims():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT id, user_id, category, sub_category, created_at 
            FROM claims 
            WHERE status = 'pending' AND (julianday('now') - julianday(created_at)) * 24 > 2 
            ORDER BY created_at ASC
        """)
        return await cursor.fetchall()

async def export_stats_to_csv() -> bytes:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
            SELECT id, user_id, category, sub_category, brand, defect_desc, purchase_date, client_wish, status, admin_name, client_name, created_at 
            FROM claims ORDER BY created_at DESC
        """)
        rows = await cursor.fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'ID', 'User ID', 'Категория', 'Подкатегория', 'Бренд', 'Дефект', 
            'Дата покупки', 'Пожелание клиента', 'Статус', 'Админ', 'Клиент', 'Дата создания'
        ])
        for row in rows:
            writer.writerow(row)
        return output.getvalue().encode('utf-8-sig')
