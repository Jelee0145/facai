"""
数据库层 — SQLite 初始化与 CRUD 操作
"""

import sqlite3
import os
import threading
from datetime import datetime, timedelta
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")
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
    # 迁移：为已有表添加 LLM 详情列
    existing_cols = [r[1] for r in db.execute("PRAGMA table_info('generation_history')").fetchall()]
    for col_name, col_def in [("llm_request", "TEXT DEFAULT ''"), ("llm_response", "TEXT DEFAULT ''"), ("tasks_detail", "TEXT DEFAULT ''")]:
        if col_name not in existing_cols:
            db.execute(f"ALTER TABLE generation_history ADD COLUMN {col_name} {col_def}")
    db.commit()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS task_store (
            task_id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            status TEXT DEFAULT 'submitting',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    db.commit()


# ========== Task Store 持久化 ==========

def save_task_progress(task_id: str, data: dict):
    db = get_db()
    import json
    db.execute(
        """INSERT OR REPLACE INTO task_store (task_id, data, status, updated_at)
           VALUES (?, ?, ?, datetime('now'))""",
        (task_id, json.dumps(data, ensure_ascii=False), data.get("status", "submitting")),
    )
    db.commit()


def load_pending_tasks() -> dict[str, dict]:
    db = get_db()
    import json
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
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    db.execute("DELETE FROM task_store WHERE created_at < ?", (cutoff,))
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
    db = get_db()
    allowed = {"name", "is_active", "daily_limit"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    updates["updated_at"] = datetime.now().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [key_id]
    db.execute(f"UPDATE api_keys SET {set_clause} WHERE id = ?", vals)
    db.commit()
    return True


def delete_key(key_id: int) -> bool:
    db = get_db()
    db.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
    db.commit()
    return db.total_changes > 0


def mark_key_used(key_id: int) -> bool:
    """原子递增配额使用量，返回是否成功（未超限）"""
    db = get_db()
    cur = db.execute(
        "UPDATE api_keys SET today_used = today_used + 1, total_used = total_used + 1, last_used_at = ?, fail_count = 0 WHERE id = ? AND today_used < daily_limit",
        (datetime.now().isoformat(), key_id),
    )
    db.commit()
    return cur.rowcount > 0


def mark_key_failed(key_id: int):
    db = get_db()
    db.execute(
        "UPDATE api_keys SET fail_count = fail_count + 1, last_used_at = ? WHERE id = ?",
        (datetime.now().isoformat(), key_id),
    )
    db.commit()
    # 连续失败 3 次自动禁用
    row = db.execute("SELECT fail_count FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    if row and row["fail_count"] >= 3:
        update_key(key_id, is_active=0)


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
):
    db = get_db()
    db.execute(
        """INSERT OR REPLACE INTO generation_history 
           (task_id, api_key_id, product_type, country, model, prompt_size, prompt_resolution,
            total_images, success_count, status, elapsed_seconds, error_msg,
            llm_request, llm_response, tasks_detail)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (task_id, api_key_id, product_type, country, model,
         prompt_size, prompt_resolution, total_images, success_count,
         status, elapsed_seconds, error_msg,
         llm_request, llm_response, tasks_detail),
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


def record_login_attempt(username: str, success: bool):
    db = get_db()
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
        if row and row["login_attempts"] >= 5:
            lock_until = (datetime.now() + timedelta(minutes=15)).isoformat()
            db.execute("UPDATE admin_users SET locked_until = ? WHERE username = ?", (lock_until, username))
    db.commit()


# ========== 系统配置 CRUD ==========

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
    db.execute("DELETE FROM custom_product_types WHERE id = ?", (type_id,))
    db.commit()
    return db.total_changes > 0


# ========== 初始化 ==========
init_db()
