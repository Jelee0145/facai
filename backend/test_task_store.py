"""Regression tests for task persistence and cleanup semantics."""

from __future__ import annotations

import importlib
import tempfile
import time
from pathlib import Path


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    import database

    with tempfile.TemporaryDirectory() as tmp:
        if hasattr(database._local, "conn"):
            database._local.conn.close()
            database._local.conn = None

        database.DB_PATH = str(Path(tmp) / "tasks.db")
        importlib.reload(database)
        database.DB_PATH = str(Path(tmp) / "tasks.db")
        database.init_db()

        database.save_task_progress("pending-task", {"status": "generating", "start_time": time.time()})
        database.save_task_progress("completed-task", {"status": "completed", "start_time": time.time()})
        database.save_task_progress("error-task", {"status": "error", "start_time": time.time()})

        db = database.get_db()
        db.execute(
            "UPDATE task_store SET created_at = datetime('now', '-25 hours') WHERE task_id = ?",
            ("pending-task",),
        )
        db.commit()

        database.delete_old_tasks(hours=24)
        rows = {
            row["task_id"]: row["status"]
            for row in db.execute("SELECT task_id, status FROM task_store").fetchall()
        }
        check("pending-task" not in rows, "expired task was not deleted")
        check(rows.get("completed-task") == "completed", "completed task should be retained when not expired")
        check(rows.get("error-task") == "error", "error task should be retained when not expired")

        pending = database.load_pending_tasks()
        check("completed-task" not in pending, "completed task was restored as pending")
        check("error-task" not in pending, "error task was restored as pending")

    print("task-store regression tests passed")


if __name__ == "__main__":
    main()
