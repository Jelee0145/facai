"""
数据库层 — SQLite 初始化与 CRUD 操作
"""

import sqlite3
import os
import threading
import json
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "data.db"))
_local = threading.local()


def get_db() -> sqlite3.Connection:
    """获取线程安全的数据库连接"""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """初始化数据库表"""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_value TEXT NOT NULL UNIQUE,
            name TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            daily_limit INTEGER DEFAULT 100,
            today_used INTEGER DEFAULT 0,
            last_used_at TEXT,
            total_used INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            balance_usd REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS generation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE,
            api_key_id INTEGER,
            product_type TEXT DEFAULT '',
            country TEXT DEFAULT '',
            model TEXT DEFAULT '',
            prompt_size TEXT DEFAULT '',
            prompt_resolution TEXT DEFAULT '',
            total_images INTEGER DEFAULT 14,
            success_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            elapsed_seconds REAL DEFAULT 0,
            error_msg TEXT DEFAULT '',
            llm_request TEXT DEFAULT '',
            llm_response TEXT DEFAULT '',
            tasks_detail TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (api_key_id) REFERENCES api_keys(id)
        );

        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'admin',
            is_active INTEGER DEFAULT 1,
            last_login TEXT,
            login_attempts INTEGER DEFAULT 0,
            locked_until TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS custom_product_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '自定义',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            phone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            is_unlimited INTEGER DEFAULT 0,
            login_attempts INTEGER DEFAULT 0,
            locked_until TEXT,
            last_login TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_wallets (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            total_recharged INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS credit_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price_fen INTEGER NOT NULL,
            points INTEGER NOT NULL,
            bonus_points INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            sort_order INTEGER DEFAULT 100,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            package_id INTEGER,
            amount_fen INTEGER NOT NULL,
            points INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            payment_provider TEXT DEFAULT 'mock',
            created_at TEXT DEFAULT (datetime('now')),
            paid_at TEXT,
            credited_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (package_id) REFERENCES credit_packages(id)
        );

        CREATE TABLE IF NOT EXISTS payment_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            provider TEXT DEFAULT 'mock',
            provider_trade_no TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            raw_payload TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (order_id) REFERENCES orders(id)
        );

        CREATE TABLE IF NOT EXISTS user_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            direction TEXT NOT NULL,
            points INTEGER NOT NULL,
            balance_after INTEGER NOT NULL,
            order_id INTEGER,
            reference_id TEXT DEFAULT '',
            remark TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (order_id) REFERENCES orders(id)
        );
    """)
    # 迁移：为已有表添加 LLM 详情列
    existing_cols = [r[1] for r in db.execute("PRAGMA table_info('generation_history')").fetchall()]
    for col_name, col_def in [
        ("llm_request", "TEXT DEFAULT ''"),
        ("llm_response", "TEXT DEFAULT ''"),
        ("tasks_detail", "TEXT DEFAULT ''"),
        ("user_id", "INTEGER"),
        ("charge_points", "INTEGER DEFAULT 0"),
        ("description_snapshot", "TEXT DEFAULT ''"),
        ("preview_images_json", "TEXT DEFAULT ''"),
        ("titles_json", "TEXT DEFAULT '[]'"),
        ("tags_json", "TEXT DEFAULT '[]'"),
        ("target_audience", "TEXT DEFAULT ''"),
        ("all_images_json", "TEXT DEFAULT '[]'"),
    ]:
        if col_name not in existing_cols:
            db.execute(f"ALTER TABLE generation_history ADD COLUMN {col_name} {col_def}")
    user_cols = [r[1] for r in db.execute("PRAGMA table_info('users')").fetchall()]
    if "is_unlimited" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN is_unlimited INTEGER DEFAULT 0")
    if "login_attempts" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN login_attempts INTEGER DEFAULT 0")
    if "locked_until" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN locked_until TEXT")
    if "last_login" not in user_cols:
        db.execute("ALTER TABLE users ADD COLUMN last_login TEXT")
    # Migration: add balance_usd to api_keys
    key_cols = [r[1] for r in db.execute("PRAGMA table_info('api_keys')").fetchall()]
    if "balance_usd" not in key_cols:
        db.execute("ALTER TABLE api_keys ADD COLUMN balance_usd REAL DEFAULT 0")
    db.commit()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS task_store (
            task_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            status TEXT DEFAULT 'submitting',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS customer_login_attempts (
            username TEXT PRIMARY KEY,
            login_attempts INTEGER DEFAULT 0,
            locked_until TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS revoked_tokens (
            jti TEXT PRIMARY KEY,
            expires_at TEXT NOT NULL,
            revoked_at TEXT DEFAULT (datetime('now'))
        );
    """)
    if not db.execute("SELECT 1 FROM credit_packages LIMIT 1").fetchone():
        db.executemany(
            """INSERT INTO credit_packages (name, price_fen, points, bonus_points, sort_order)
               VALUES (?, ?, ?, ?, ?)""",
            [
                ("体验包", 990, 100, 0, 10),
                ("标准包", 2990, 360, 60, 20),
                ("增长包", 5990, 820, 220, 30),
            ],
        )
    if db.execute("SELECT value FROM system_config WHERE key = ?", ("generation_cost_points",)).fetchone() is None:
        db.execute(
            "INSERT INTO system_config (key, value, updated_at) VALUES (?, ?, datetime('now'))",
            ("generation_cost_points", "10"),
        )
    # Migrations for existing databases
    try:
        db.execute("ALTER TABLE users ADD COLUMN note TEXT DEFAULT ''")
        db.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Create indexes for high-traffic queries (idempotent)
    db.executescript("""
        CREATE INDEX IF NOT EXISTS idx_history_user ON generation_history(user_id);
        CREATE INDEX IF NOT EXISTS idx_history_created ON generation_history(created_at);
        CREATE INDEX IF NOT EXISTS idx_ledger_user ON user_ledger(user_id);
        CREATE INDEX IF NOT EXISTS idx_ledger_created ON user_ledger(created_at);
        CREATE INDEX IF NOT EXISTS idx_task_status ON task_store(status);
        CREATE INDEX IF NOT EXISTS idx_task_created ON task_store(created_at);
        CREATE INDEX IF NOT EXISTS idx_revoked_expires ON revoked_tokens(expires_at);
    """)
    db.commit()


# ========== Task Store 持久化 ==========

def save_task_progress(task_id: str, data: dict):
    db = get_db()
    db.execute(
        """INSERT INTO task_store (task_id, data, status, updated_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(task_id) DO UPDATE SET
             data = excluded.data,
             status = excluded.status,
             updated_at = datetime('now')""",
        (task_id, json.dumps(data, ensure_ascii=False), data.get("status", "submitting")),
    )
    db.commit()


def load_pending_tasks() -> dict[str, dict]:
    db = get_db()
    rows = db.execute(
        "SELECT task_id, data FROM task_store WHERE status NOT IN ('completed', 'error')"
    ).fetchall()
    result = {}
    for row in rows:
        try:
            result[row["task_id"]] = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def delete_old_tasks(hours: int = 24):
    db = get_db()
    db.execute("DELETE FROM task_store WHERE created_at < datetime('now', ?)", (f"-{int(hours)} hours",))
    db.commit()


# ========== API Keys CRUD ==========

def mask_api_key(key_value: str) -> str:
    """脱敏 API Key：仅保留前 4 位和后 4 位"""
    if not key_value or len(key_value) < 12:
        return "****"
    return key_value[:4] + "****" + key_value[-4:]


def get_all_keys() -> list[dict]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM api_keys ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_keys_masked() -> list[dict]:
    """返回脱敏后的 API Key 列表"""
    keys = get_all_keys()
    for k in keys:
        k["key_value"] = mask_api_key(k["key_value"])
    return keys


def get_active_keys() -> list[dict]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM api_keys WHERE is_active = 1 ORDER BY last_used_at ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def add_key(key_value: str, name: str = "", daily_limit: int = 100) -> int:
    db = get_db()
    cur = db.execute(
        "INSERT INTO api_keys (key_value, name, daily_limit) VALUES (?, ?, ?)",
        (key_value.strip(), name.strip(), daily_limit),
    )
    db.commit()
    return cur.lastrowid


def update_key(key_id: int, **kwargs) -> bool:
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[BALANCE] update_key called with key_id={key_id}, kwargs={kwargs}")
    db = get_db()
    allowed = {"name", "is_active", "daily_limit", "balance_usd"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    logger.info(f"[BALANCE] updates after filtering: {updates}")
    if not updates:
        logger.warning(f"[BALANCE] No allowed fields to update for key_id={key_id}")
        return False
    if updates.get("is_active") == 1:
        updates["fail_count"] = 0
    # Reset daily usage when balance is manually updated
    if "balance_usd" in updates:
        updates["today_used"] = 0
    updates["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [key_id]
    logger.info(f"[BALANCE] SQL: UPDATE api_keys SET {set_clause} WHERE id = ?")
    logger.info(f"[BALANCE] Values: {vals}")
    cur = db.execute(f"UPDATE api_keys SET {set_clause} WHERE id = ?", vals)
    db.commit()
    logger.info(f"[BALANCE] Updated {cur.rowcount} rows")
    return cur.rowcount > 0


def delete_key(key_id: int) -> bool:
    db = get_db()
    cur = db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    db.commit()
    return cur.rowcount > 0


def mark_key_used(key_id: int) -> bool:
    """原子递增配额使用量，返回是否成功（未超限）"""
    db = get_db()
    cur = db.execute(
        """UPDATE api_keys
           SET today_used = today_used + 1, total_used = total_used + 1,
               last_used_at = ?, fail_count = MAX(fail_count - 1, 0)
           WHERE id = ? AND today_used < daily_limit""",
        (datetime.now().isoformat(), key_id),
    )
    db.commit()
    return cur.rowcount > 0


def mark_key_failed(key_id: int):
    db = get_db()
    cur = db.execute(
        """UPDATE api_keys
           SET fail_count = fail_count + 1,
               last_used_at = ?,
               is_active = CASE WHEN fail_count + 1 >= 3 THEN 0 ELSE is_active END
           WHERE id = ?""",
        (datetime.now().isoformat(), key_id),
    )
    db.commit()
    if cur.rowcount > 0:
        row = db.execute("SELECT fail_count, is_active FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        if row and row["is_active"] == 0:
            print(f"[KEY] API Key {key_id} disabled after {row['fail_count']} consecutive failures")


def reset_daily_usage():
    db = get_db()
    db.execute("UPDATE api_keys SET today_used = 0")
    db.commit()


def get_key_by_value(value: str) -> Optional[dict]:
    db = get_db()
    row = db.execute("SELECT * FROM api_keys WHERE key_value = ?", (value,)).fetchone()
    return dict(row) if row else None


# ========== 历史记录 CRUD ==========

def add_history(
    task_id: str,
    api_key_id: Optional[int] = None,
    user_id: Optional[int] = None,
    product_type: str = "",
    country: str = "",
    model: str = "",
    prompt_size: str = "",
    prompt_resolution: str = "",
    total_images: int = 14,
    success_count: int = 0,
    status: str = "pending",
    elapsed_seconds: float = 0,
    error_msg: str = "",
    llm_request: str = "",
    llm_response: str = "",
    tasks_detail: str = "",
    charge_points: int = 0,
    description_snapshot: str = "",
    preview_images_json: str = "",
    titles_json: str = "[]",
    tags_json: str = "[]",
    target_audience: str = "",
    all_images_json: str = "[]",
):
    db = get_db()
    db.execute(
        """INSERT INTO generation_history
           (task_id, api_key_id, user_id, product_type, country, model, prompt_size, prompt_resolution,
            total_images, success_count, status, elapsed_seconds, error_msg,
            llm_request, llm_response, tasks_detail, charge_points, description_snapshot, preview_images_json,
            titles_json, tags_json, target_audience, all_images_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(task_id) DO UPDATE SET
             api_key_id = excluded.api_key_id,
             user_id = excluded.user_id,
             product_type = excluded.product_type,
             country = excluded.country,
             model = excluded.model,
             prompt_size = excluded.prompt_size,
             prompt_resolution = excluded.prompt_resolution,
             total_images = excluded.total_images,
             success_count = excluded.success_count,
             status = excluded.status,
             elapsed_seconds = excluded.elapsed_seconds,
             error_msg = excluded.error_msg,
             llm_request = excluded.llm_request,
             llm_response = excluded.llm_response,
             tasks_detail = excluded.tasks_detail,
             charge_points = excluded.charge_points,
             description_snapshot = excluded.description_snapshot,
             preview_images_json = excluded.preview_images_json,
             titles_json = excluded.titles_json,
             tags_json = excluded.tags_json,
             target_audience = excluded.target_audience,
             all_images_json = excluded.all_images_json""",
        (task_id, api_key_id, user_id, product_type, country, model,
         prompt_size, prompt_resolution, total_images, success_count,
         status, elapsed_seconds, error_msg,
         llm_request, llm_response, tasks_detail, charge_points,
         description_snapshot, preview_images_json,
         titles_json, tags_json, target_audience, all_images_json),
    )
    db.commit()


def get_history(page: int = 1, per_page: int = 20, status: str = "", search: str = "") -> dict:
    db = get_db()
    conditions = []
    params = []
    if status:
        conditions.append("h.status = ?")
        params.append(status)
    if search:
        safe_search = search.replace("%", "\\%").replace("_", "\\_")
        conditions.append("(h.product_type LIKE ? ESCAPE '\\' OR h.task_id LIKE ? ESCAPE '\\')")
        params.extend([f"%{safe_search}%", f"%{safe_search}%"])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    count_row = db.execute(f"SELECT COUNT(*) as cnt FROM generation_history h {where}", params).fetchone()
    total = count_row["cnt"] if count_row else 0

    offset = (page - 1) * per_page
    rows = db.execute(
        f"""SELECT h.*, k.name as key_name 
            FROM generation_history h 
            LEFT JOIN api_keys k ON h.api_key_id = k.id 
            {where} 
            ORDER BY h.created_at DESC 
            LIMIT ? OFFSET ?""",
        params + [per_page, offset],
    ).fetchall()

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "items": [dict(r) for r in rows],
    }


def get_history_detail(history_id: int) -> Optional[dict]:
    """获取单条历史记录的完整详情"""
    db = get_db()
    row = db.execute(
        """SELECT h.*, k.name as key_name 
            FROM generation_history h 
            LEFT JOIN api_keys k ON h.api_key_id = k.id 
            WHERE h.id = ?""",
        (history_id,),
    ).fetchone()
    return dict(row) if row else None


def update_history_detail(history_id: int, **kwargs) -> bool:
    """更新历史记录详情字段"""
    db = get_db()
    allowed = {"llm_request", "llm_response", "tasks_detail"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [history_id]
    db.execute(f"UPDATE generation_history SET {set_clause} WHERE id = ?", vals)
    db.commit()
    return True


def get_dashboard_stats() -> dict:
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    total_keys = db.execute("SELECT COUNT(*) as cnt FROM api_keys").fetchone()["cnt"]
    active_keys = db.execute("SELECT COUNT(*) as cnt FROM api_keys WHERE is_active = 1").fetchone()["cnt"]
    today_generations = db.execute(
        "SELECT COUNT(*) as cnt FROM generation_history WHERE date(created_at) = ?", (today,)
    ).fetchone()["cnt"]
    today_success = db.execute(
        "SELECT COUNT(*) as cnt FROM generation_history WHERE date(created_at) = ? AND status = 'completed'", (today,)
    ).fetchone()["cnt"]
    today_avg_time = db.execute(
        "SELECT AVG(elapsed_seconds) as avg FROM generation_history WHERE date(created_at) = ? AND status = 'completed'", (today,)
    ).fetchone()["avg"] or 0
    total_generations = db.execute("SELECT COUNT(*) as cnt FROM generation_history").fetchone()["cnt"]

    return {
        "total_keys": total_keys,
        "active_keys": active_keys,
        "today_generations": today_generations,
        "today_success": today_success,
        "today_success_rate": round(today_success / today_generations * 100, 1) if today_generations else 0,
        "today_avg_time": round(today_avg_time, 1),
        "total_generations": total_generations,
    }


# ========== 用户管理 ==========

def get_user(username: str) -> Optional[dict]:
    db = get_db()
    row = db.execute("SELECT * FROM admin_users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def create_user(username: str, password_hash: str) -> int:
    db = get_db()
    cur = db.execute(
        "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
        (username, password_hash),
    )
    db.commit()
    return cur.lastrowid


def update_admin_password(username: str, password_hash: str) -> bool:
    db = get_db()
    cur = db.execute(
        "UPDATE admin_users SET password_hash = ?, login_attempts = 0, locked_until = NULL WHERE username = ?",
        (password_hash, username),
    )
    db.commit()
    return cur.rowcount > 0


def record_login_attempt(username: str, success: bool):
    db = get_db()
    from security import LOGIN_MAX_ATTEMPTS, LOGIN_LOCK_MINUTES
    if success:
        db.execute(
            "UPDATE admin_users SET login_attempts = 0, locked_until = NULL, last_login = ? WHERE username = ?",
            (datetime.now().isoformat(), username),
        )
    else:
        db.execute(
            "UPDATE admin_users SET login_attempts = login_attempts + 1 WHERE username = ?",
            (username,),
        )
        row = db.execute("SELECT login_attempts FROM admin_users WHERE username = ?", (username,)).fetchone()
        if row and row["login_attempts"] >= LOGIN_MAX_ATTEMPTS:
            lock_until = (datetime.now() + timedelta(minutes=LOGIN_LOCK_MINUTES)).isoformat()
            db.execute("UPDATE admin_users SET locked_until = ? WHERE username = ?", (lock_until, username))
    db.commit()


def record_customer_login_attempt(username: str, success: bool):
    """前台用户登录尝试记录 — 对不存在用户名也做锁定"""
    db = get_db()
    from security import LOGIN_MAX_ATTEMPTS, LOGIN_LOCK_MINUTES
    if success:
        db.execute(
            "UPDATE users SET login_attempts = 0, locked_until = NULL, last_login = ? WHERE username = ?",
            (datetime.now().isoformat(), username),
        )
        db.execute(
            "DELETE FROM customer_login_attempts WHERE username = ?",
            (username,),
        )
    else:
        db.execute(
            """INSERT INTO customer_login_attempts (username, login_attempts, updated_at)
               VALUES (?, 1, datetime('now'))
               ON CONFLICT(username) DO UPDATE SET
                 login_attempts = login_attempts + 1,
                 updated_at = datetime('now')""",
            (username,),
        )
        # Sync to real user if exists
        db.execute(
            "UPDATE users SET login_attempts = login_attempts + 1 WHERE username = ?",
            (username,),
        )
        row = db.execute(
            "SELECT login_attempts FROM customer_login_attempts WHERE username = ?",
            (username,),
        ).fetchone()
        if row and row["login_attempts"] >= LOGIN_MAX_ATTEMPTS:
            lock_until = (datetime.now() + timedelta(minutes=LOGIN_LOCK_MINUTES)).isoformat()
            db.execute(
                "UPDATE customer_login_attempts SET locked_until = ? WHERE username = ?",
                (lock_until, username),
            )
            db.execute(
                "UPDATE users SET locked_until = ? WHERE username = ?",
                (lock_until, username),
            )
    db.commit()


def get_customer_login_lock(username: str) -> Optional[str]:
    """Return the later locked_until from customer_login_attempts or users, or None."""
    db = get_db()
    attempt_row = db.execute(
        "SELECT locked_until FROM customer_login_attempts WHERE username = ?",
        (username,),
    ).fetchone()
    user_row = db.execute(
        "SELECT locked_until FROM users WHERE username = ?",
        (username,),
    ).fetchone()
    times = []
    if attempt_row and attempt_row["locked_until"]:
        times.append(attempt_row["locked_until"])
    if user_row and user_row["locked_until"]:
        times.append(user_row["locked_until"])
    return max(times) if times else None


# ========== 管理员-用户管理 ==========

def list_all_users() -> list[dict]:
    """获取所有用户（不含 password_hash），关联 wallet 余额"""
    db = get_db()
    rows = db.execute("""
        SELECT u.id, u.username, u.phone, u.email, u.status, u.is_unlimited,
               u.last_login, u.created_at, u.note,
               COALESCE(w.balance, 0) AS balance,
               COALESCE(w.total_recharged, 0) AS total_recharged,
               COALESCE(w.total_spent, 0) AS total_spent
        FROM users u
        LEFT JOIN user_wallets w ON u.id = w.user_id
        ORDER BY u.id ASC
    """).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["is_unlimited"] = bool(d.get("is_unlimited"))
        result.append(d)
    return result


def admin_create_user(username: str, password_hash: str, phone: str = "", email: str = "", note: str = "") -> int:
    """管理员创建用户 + 自动创建 wallet"""
    db = get_db()
    try:
        cur = db.execute(
            """INSERT INTO users (username, password_hash, phone, email, note, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (username.strip(), password_hash, phone.strip(), email.strip(), note.strip()),
        )
        user_id = int(cur.lastrowid)
        db.execute("INSERT INTO user_wallets (user_id) VALUES (?)", (user_id,))
        db.commit()
        return user_id
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ValueError("username_exists") from exc


def update_user_status(user_id: int, status: str) -> bool:
    """更新用户 status（'active'/'frozen'）"""
    db = get_db()
    cur = db.execute(
        "UPDATE users SET status = ?, updated_at = datetime('now') WHERE id = ?",
        (status, user_id),
    )
    db.commit()
    return cur.rowcount > 0


def update_user_note(user_id: int, note: str) -> bool:
    """更新用户备注"""
    db = get_db()
    cur = db.execute(
        "UPDATE users SET note = ?, updated_at = datetime('now') WHERE id = ?",
        (note.strip(), user_id),
    )
    db.commit()
    return cur.rowcount > 0


def delete_user(user_id: int) -> bool:
    """删除用户 + 关联数据（按外键依赖顺序删除）"""
    db = get_db()
    user = db.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        return False
    username = user["username"]
    try:
        db.execute("BEGIN IMMEDIATE")
        # 先收集该用户的 order_id，以便删除关联的 payment_transactions
        order_ids = [r["id"] for r in db.execute("SELECT id FROM orders WHERE user_id = ?", (user_id,)).fetchall()]
        # 按外键依赖顺序删除
        if order_ids:
            placeholders = ",".join("?" * len(order_ids))
            db.execute(f"DELETE FROM payment_transactions WHERE order_id IN ({placeholders})", order_ids)
        db.execute("DELETE FROM user_ledger WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM generation_history WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM orders WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM user_wallets WHERE user_id = ?", (user_id,))
        db.execute("DELETE FROM customer_login_attempts WHERE username = ?", (username,))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        # 清理过期的已撤销 token，保持 revoked_tokens 表整洁
        db.execute("DELETE FROM revoked_tokens WHERE expires_at < datetime('now')")
        db.commit()
        return True
    except Exception:
        db.rollback()
        raise


# ========== 系统配置 CRUD ==========

def get_customer_by_username(username: str) -> Optional[dict]:
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def get_customer_by_id(user_id: int) -> Optional[dict]:
    db = get_db()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def create_customer(username: str, password_hash: str, phone: str = "", email: str = "") -> int:
    db = get_db()
    try:
        cur = db.execute(
            """INSERT INTO users (username, password_hash, phone, email, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))""",
            (username.strip(), password_hash, phone.strip(), email.strip()),
        )
        user_id = int(cur.lastrowid)
        db.execute("INSERT INTO user_wallets (user_id) VALUES (?)", (user_id,))
        db.commit()
        return user_id
    except sqlite3.IntegrityError as exc:
        db.rollback()
        raise ValueError("username_exists") from exc


def ensure_customer(username: str, password_hash: str, phone: str = "", email: str = "", is_unlimited: bool = False) -> int:
    db = get_db()
    row = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if row:
        db.execute(
            """UPDATE users
               SET password_hash = ?, phone = ?, email = ?, status = 'active',
                   is_unlimited = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (password_hash, phone, email, 1 if is_unlimited else 0, row["id"]),
        )
        db.execute("INSERT OR IGNORE INTO user_wallets (user_id) VALUES (?)", (row["id"],))
        db.commit()
        return int(row["id"])
    user_id = create_customer(username, password_hash, phone=phone, email=email)
    if is_unlimited:
        db.execute("UPDATE users SET is_unlimited = 1 WHERE id = ?", (user_id,))
        db.commit()
    return user_id


def get_wallet(user_id: int) -> dict:
    db = get_db()
    user = db.execute("SELECT is_unlimited FROM users WHERE id = ?", (user_id,)).fetchone()
    row = db.execute("SELECT * FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        wallet = dict(row)
        wallet["is_unlimited"] = bool(user and user["is_unlimited"])
        if wallet["is_unlimited"]:
            wallet["balance"] = 999999999
        return wallet
    db.execute("INSERT INTO user_wallets (user_id) VALUES (?)", (user_id,))
    db.commit()
    is_unlimited = bool(user and user["is_unlimited"])
    return {"user_id": user_id, "balance": 999999999 if is_unlimited else 0, "total_recharged": 0, "total_spent": 0, "is_unlimited": is_unlimited}


def get_generation_cost_points() -> int:
    row = get_config("generation_cost_points")
    try:
        return max(1, int(row or "10"))
    except ValueError:
        return 10


def list_credit_packages(include_inactive: bool = False) -> list[dict]:
    db = get_db()
    where = "" if include_inactive else "WHERE status = 'active'"
    rows = db.execute(
        f"SELECT * FROM credit_packages {where} ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_credit_package(
    name: str,
    price_fen: int,
    points: int,
    bonus_points: int = 0,
    status: str = "active",
    sort_order: int = 100,
    package_id: Optional[int] = None,
) -> int:
    db = get_db()
    if package_id:
        cur = db.execute(
            """UPDATE credit_packages
               SET name = ?, price_fen = ?, points = ?, bonus_points = ?,
                   status = ?, sort_order = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (name.strip(), price_fen, points, bonus_points, status, sort_order, package_id),
        )
        db.commit()
        if cur.rowcount == 0:
            raise ValueError("package_not_found")
        return package_id
    cur = db.execute(
        """INSERT INTO credit_packages
           (name, price_fen, points, bonus_points, status, sort_order)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name.strip(), price_fen, points, bonus_points, status, sort_order),
    )
    db.commit()
    return int(cur.lastrowid)


def delete_credit_package(package_id: int) -> bool:
    """硬删除套餐，若有订单关联则返回 False 不删除。"""
    db = get_db()
    has_orders = db.execute(
        "SELECT 1 FROM orders WHERE package_id = ? LIMIT 1", (package_id,)
    ).fetchone()
    if has_orders:
        return False
    cur = db.execute("DELETE FROM credit_packages WHERE id = ?", (package_id,))
    db.commit()
    return cur.rowcount > 0


def get_order_by_no(order_no: str) -> Optional[dict]:
    db = get_db()
    row = db.execute(
        """SELECT o.*, p.name as package_name
           FROM orders o
           LEFT JOIN credit_packages p ON p.id = o.package_id
           WHERE o.order_no = ?""",
        (order_no,),
    ).fetchone()
    return dict(row) if row else None


def create_order(user_id: int, package_id: int, order_no: str) -> dict:
    db = get_db()
    pkg = db.execute(
        "SELECT * FROM credit_packages WHERE id = ? AND status = 'active'",
        (package_id,),
    ).fetchone()
    if not pkg:
        raise ValueError("package_not_found")
    points = int(pkg["points"]) + int(pkg["bonus_points"])
    cur = db.execute(
        """INSERT INTO orders (order_no, user_id, package_id, amount_fen, points)
           VALUES (?, ?, ?, ?, ?)""",
        (order_no, user_id, package_id, int(pkg["price_fen"]), points),
    )
    order_id = int(cur.lastrowid)
    db.execute(
        """INSERT INTO payment_transactions (order_id, provider, status, raw_payload)
           VALUES (?, 'mock', 'pending', ?)""",
        (order_id, json.dumps({"source": "placeholder"}, ensure_ascii=False)),
    )
    db.commit()
    return get_order_by_no(order_no) or {}


def mark_order_paid(order_no: str, provider_trade_no: str = "") -> dict:
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        order = db.execute("SELECT * FROM orders WHERE order_no = ?", (order_no,)).fetchone()
        if not order:
            raise ValueError("order_not_found")
        order_dict = dict(order)
        if order_dict["status"] == "credited":
            db.commit()
            return get_order_by_no(order_no) or order_dict
        if order_dict["status"] not in ("pending", "paid"):
            raise ValueError("order_not_creditable")
        db.execute(
            """UPDATE orders
               SET status = 'credited', paid_at = COALESCE(paid_at, datetime('now')),
                   credited_at = datetime('now')
               WHERE id = ?""",
            (order_dict["id"],),
        )
        db.execute(
            """UPDATE payment_transactions
               SET status = 'paid', provider_trade_no = ?, updated_at = datetime('now')
               WHERE order_id = ?""",
            (provider_trade_no, order_dict["id"]),
        )
        wallet = db.execute("SELECT balance FROM user_wallets WHERE user_id = ?", (order_dict["user_id"],)).fetchone()
        balance = int(wallet["balance"] if wallet else 0)
        new_balance = balance + int(order_dict["points"])
        db.execute("INSERT OR IGNORE INTO user_wallets (user_id, balance) VALUES (?, 0)", (order_dict["user_id"],))
        db.execute(
            """UPDATE user_wallets
               SET balance = ?, total_recharged = total_recharged + ?, updated_at = datetime('now')
               WHERE user_id = ?""",
            (new_balance, int(order_dict["points"]), order_dict["user_id"]),
        )
        db.execute(
            """INSERT INTO user_ledger
               (user_id, type, direction, points, balance_after, order_id, remark)
               VALUES (?, 'recharge', 'in', ?, ?, ?, ?)""",
            (order_dict["user_id"], int(order_dict["points"]), new_balance, order_dict["id"], f"充值订单 {order_no}"),
        )
        db.commit()
        return get_order_by_no(order_no) or order_dict
    except Exception:
        db.rollback()
        raise


def charge_generation(user_id: int, task_id: str, points: int, remark: str = "") -> dict:
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        user = db.execute("SELECT is_unlimited FROM users WHERE id = ?", (user_id,)).fetchone()
        if user and user["is_unlimited"]:
            cur = db.execute(
                """INSERT INTO user_ledger
                   (user_id, type, direction, points, balance_after, reference_id, remark)
                   VALUES (?, 'consume', 'out', 0, 999999999, ?, ?)""",
                (user_id, task_id, remark or "无限额度生成"),
            )
            db.commit()
            return {"ledger_id": int(cur.lastrowid), "balance": 999999999, "is_unlimited": True}
        wallet = db.execute("SELECT balance FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
        balance = int(wallet["balance"] if wallet else 0)
        if balance < points:
            raise ValueError("insufficient_balance")
        new_balance = balance - points
        db.execute(
            """UPDATE user_wallets
               SET balance = ?, total_spent = total_spent + ?, updated_at = datetime('now')
               WHERE user_id = ?""",
            (new_balance, points, user_id),
        )
        cur = db.execute(
            """INSERT INTO user_ledger
               (user_id, type, direction, points, balance_after, reference_id, remark)
               VALUES (?, 'consume', 'out', ?, ?, ?, ?)""",
            (user_id, points, new_balance, task_id, remark),
        )
        db.commit()
        return {"ledger_id": int(cur.lastrowid), "balance": new_balance}
    except Exception:
        db.rollback()
        raise


def refund_generation(user_id: int, task_id: str, points: int, remark: str = "") -> dict:
    db = get_db()
    if points <= 0:
        return {"status": "skipped", "refunded": False, "points": 0, "reason": "no_charge"}
    try:
        db.execute("BEGIN IMMEDIATE")
        # Unlimited users: skip refund entirely (consumption was recorded as 0)
        user = db.execute("SELECT is_unlimited FROM users WHERE id = ?", (user_id,)).fetchone()
        if user and user["is_unlimited"]:
            db.commit()
            return {"status": "skipped_unlimited", "refunded": False, "points": 0, "reason": "unlimited_user"}

        existing = db.execute(
            """SELECT id, balance_after FROM user_ledger
               WHERE user_id = ? AND type = 'refund' AND reference_id = ?
               LIMIT 1""",
            (user_id, task_id),
        ).fetchone()
        if existing:
            db.commit()
            return {
                "status": "already_refunded",
                "refunded": False,
                "ledger_id": int(existing["id"]),
                "balance": int(existing["balance_after"]),
                "points": points,
            }

        wallet = db.execute("SELECT balance FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()
        balance = int(wallet["balance"] if wallet else 0)
        new_balance = balance + points
        db.execute("INSERT OR IGNORE INTO user_wallets (user_id, balance) VALUES (?, 0)", (user_id,))
        db.execute(
            """UPDATE user_wallets
               SET balance = ?, total_spent = MAX(total_spent - ?, 0), updated_at = datetime('now')
               WHERE user_id = ?""",
            (new_balance, points, user_id),
        )
        cur = db.execute(
            """INSERT INTO user_ledger
               (user_id, type, direction, points, balance_after, reference_id, remark)
               VALUES (?, 'refund', 'in', ?, ?, ?, ?)""",
            (user_id, points, new_balance, task_id, remark),
        )
        db.commit()
        return {
            "status": "refunded",
            "refunded": True,
            "ledger_id": int(cur.lastrowid),
            "balance": new_balance,
            "points": points,
        }
    except Exception:
        db.rollback()
        raise


def ensure_refund_once(task_data: dict, user_id: int, task_id: str, points: int, remark: str = "") -> dict:
    """Refund a charged generation task at most once using the ledger as source of truth."""
    result = refund_generation(user_id, task_id, points, remark)
    task_data["refunded"] = result["status"] in ("refunded", "already_refunded", "skipped", "skipped_unlimited")
    task_data["refund_status"] = result["status"]
    return result


def list_user_history(user_id: int, limit: int = 30) -> list[dict]:
    db = get_db()
    rows = db.execute(
        """SELECT id, task_id, product_type, description_snapshot, preview_images_json,
                  charge_points, status, created_at
           FROM generation_history
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["preview_images"] = json.loads(item.pop("preview_images_json") or "[]")[:3]
        except (json.JSONDecodeError, TypeError):
            item["preview_images"] = []
        items.append(item)
    return items


def get_user_history_detail(user_id: int, history_id: int) -> Optional[dict]:
    """获取单条历史记录详情（含 titles/tags/target_audience/all_images）"""
    db = get_db()
    row = db.execute(
        "SELECT * FROM generation_history WHERE id = ? AND user_id = ?",
        (history_id, user_id),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    for field in ("titles_json", "tags_json", "all_images_json", "preview_images_json"):
        try:
            item[field] = json.loads(item.get(field) or "[]")
        except (json.JSONDecodeError, TypeError):
            item[field] = []
    return item


def list_user_ledger(user_id: int, limit: int = 50) -> list[dict]:
    db = get_db()
    rows = db.execute(
        """SELECT l.*, o.order_no, o.amount_fen, o.status as order_status, p.name as package_name
           FROM user_ledger l
           LEFT JOIN orders o ON o.id = l.order_id
           LEFT JOIN credit_packages p ON p.id = o.package_id
           WHERE l.user_id = ?
           ORDER BY l.created_at DESC
           LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def list_user_orders(user_id: int, limit: int = 30) -> list[dict]:
    db = get_db()
    rows = db.execute(
        """SELECT o.*, p.name as package_name
           FROM orders o
           LEFT JOIN credit_packages p ON p.id = o.package_id
           WHERE o.user_id = ?
           ORDER BY o.created_at DESC
           LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def list_all_orders(limit: int = 100) -> list[dict]:
    db = get_db()
    rows = db.execute(
        """SELECT o.*, u.username, p.name as package_name
           FROM orders o
           LEFT JOIN users u ON u.id = o.user_id
           LEFT JOIN credit_packages p ON p.id = o.package_id
           ORDER BY o.created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_config(key: str) -> Optional[str]:
    """读取系统配置项"""
    db = get_db()
    row = db.execute("SELECT value FROM system_config WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_config(key: str, value: str) -> None:
    """写入/更新系统配置项"""
    db = get_db()
    db.execute(
        """INSERT INTO system_config (key, value, updated_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')""",
        (key, value),
    )
    db.commit()


def get_all_configs() -> dict[str, str]:
    """获取所有系统配置"""
    db = get_db()
    rows = db.execute("SELECT key, value FROM system_config").fetchall()
    return {row["key"]: row["value"] for row in rows}


# ========== Token Revocation ==========

def revoke_jti(jti: str, expires_at: str) -> None:
    """Revoke a JWT by its jti claim. Idempotent."""
    db = get_db()
    db.execute(
        """INSERT OR IGNORE INTO revoked_tokens (jti, expires_at)
           VALUES (?, ?)""",
        (jti, expires_at),
    )
    db.commit()


def is_jti_revoked(jti: str) -> bool:
    """Check if a JWT jti has been revoked."""
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM revoked_tokens WHERE jti = ?", (jti,)
    ).fetchone()
    return row is not None


def cleanup_expired_revoked_tokens() -> int:
    """Delete revoked tokens whose expiry has passed. Returns count deleted."""
    db = get_db()
    cur = db.execute(
        "DELETE FROM revoked_tokens WHERE expires_at < datetime('now')"
    )
    db.commit()
    return cur.rowcount


# ========== 自定义产品类型 CRUD ==========

def get_all_custom_types() -> list[dict]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM custom_product_types ORDER BY created_at ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def add_custom_type(label: str, category: str) -> int:
    db = get_db()
    cur = db.execute(
        "INSERT INTO custom_product_types (label, category) VALUES (?, ?)",
        (label.strip(), category.strip()),
    )
    db.commit()
    return cur.lastrowid


def delete_custom_type(type_id: int) -> bool:
    db = get_db()
    cur = db.execute("DELETE FROM custom_product_types WHERE id = ?", (type_id,))
    db.commit()
    return cur.rowcount > 0


# ========== 初始化 ==========
# 注意：init_db() 不再在模块导入时自动调用
# 由应用启动时显式调用，避免模块导入时的副作用
