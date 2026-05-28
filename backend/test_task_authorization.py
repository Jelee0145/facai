"""Regression tests for generation task ownership checks."""

from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path

from fastapi import HTTPException


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    os.environ.setdefault("JWT_SECRET", "test-secret-for-task-authorization")
    os.environ.setdefault("API_AUTH_TOKEN", "test-api-auth")

    import database

    with tempfile.TemporaryDirectory() as tmp:
        if hasattr(database._local, "conn") and database._local.conn is not None:
            database._local.conn.close()
            database._local.conn = None

        database.DB_PATH = str(Path(tmp) / "tasks-auth.db")
        importlib.reload(database)
        database.DB_PATH = str(Path(tmp) / "tasks-auth.db")
        database.init_db()

        import main as app_main

        app_main.task_store.clear()
        app_main.task_store["task-a"] = {
            "status": "generating",
            "total": 14,
            "completed": 0,
            "start_time": 0,
            "images": [],
            "user_id": 1,
        }

        owner_task = app_main.get_task_for_request("task-a", request=None, user={"id": 1})
        check(owner_task["user_id"] == 1, "owner should be allowed to read task")

        try:
            app_main.get_task_for_request("task-a", request=None, user={"id": 2})
        except HTTPException as exc:
            check(exc.status_code == 404, f"wrong owner status was {exc.status_code}")
        else:
            raise AssertionError("wrong owner was allowed to read task")

        try:
            app_main.get_task_for_request("missing", request=None, user={"id": 1})
        except HTTPException as exc:
            check(exc.status_code == 404, f"missing task status was {exc.status_code}")
        else:
            raise AssertionError("missing task was returned")

        if hasattr(database._local, "conn") and database._local.conn is not None:
            database._local.conn.close()
            database._local.conn = None

    print("task authorization regression tests passed")


if __name__ == "__main__":
    main()
