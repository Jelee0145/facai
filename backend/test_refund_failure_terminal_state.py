"""Regression tests: _run_generation_background reaches terminal state even when refund throws."""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
import time
import types
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests-only")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    import database

    with tempfile.TemporaryDirectory() as tmp:
        if hasattr(database._local, "conn") and database._local.conn is not None:
            database._local.conn.close()
            database._local.conn = None

        db_path = str(Path(tmp) / "terminal.db")
        database.DB_PATH = db_path
        importlib.reload(database)
        database.DB_PATH = db_path
        database.init_db()

        # Prepare user
        user_id = database.create_customer("terminal-test-user", "unused-hash")
        db = database.get_db()
        db.execute("UPDATE user_wallets SET balance = 100 WHERE user_id = ?", (user_id,))
        db.commit()

        # Import main module and set it up to use the temp DB
        import main as m

        # Ensure main's database module uses our temp DB
        m.save_task_progress = database.save_task_progress
        m.ensure_refund_once = database.ensure_refund_once
        m.add_history = database.add_history
        m.get_config = database.get_config
        m.get_generation_cost_points = database.get_generation_cost_points

        # Create a task in task_store
        task_id = "test-terminal-task"
        charge_points = 10
        m.task_store[task_id] = {
            "status": "submitting",
            "total": 14,
            "completed": 0,
            "start_time": time.time() - 10,
            "images": [{"index": i, "status": "pending", "url": None, "name": f"img{i}"} for i in range(14)],
            "error": None,
            "result": None,
            "user_id": user_id,
            "charge_points": charge_points,
        }
        database.charge_generation(user_id, task_id, charge_points, "test charge")

        # Monkeypatch: apimart_upload_image raises immediately (simulates generation failure)
        async def broken_upload(image_url: str) -> str:
            raise RuntimeError("simulated upload/generation failure")

        # Monkeypatch: ensure_refund_once raises (simulates refund DB failure)
        def broken_refund(task_data, uid, tid, points, remark=""):
            raise RuntimeError("simulated refund DB failure")

        # Monkeypatch: push_event collects events
        collected_events: list[dict] = []

        def fake_push_event(tid: str, data: dict):
            collected_events.append(data)

        # Save originals
        orig_upload = m.apimart_upload_image
        orig_refund = m.ensure_refund_once
        orig_push = m.push_event

        m.apimart_upload_image = broken_upload
        m.ensure_refund_once = broken_refund
        m.push_event = fake_push_event

        # Create a minimal GenerateRequest-like object
        req = types.SimpleNamespace(
            image_url="https://example.com/test.jpg",
            product_type="test",
            country="japan",
            model="general",
            generate_type="all",
            style_index=0,
            prompt_size="auto",
            prompt_resolution="1k",
        )

        try:
            asyncio.run(m._run_generation_background(task_id, req, user_id, charge_points))
        except Exception as e:
            # _run_generation_background should NOT propagate exceptions
            check(False, f"_run_generation_background raised: {e}")

        # Assert: task in memory reached terminal state
        task = m.task_store.get(task_id)
        check(task is not None, "task disappeared from task_store")
        check(task["status"] == "error", f"expected status=error, got {task['status']}")
        check(task.get("error"), f"expected error message, got {task.get('error')}")

        # Assert: refund_status is failed (because ensure_refund_once threw)
        check(task.get("refund_status") == "failed", f"expected refund_status=failed, got {task.get('refund_status')}")
        check(task.get("refund_error"), f"expected refund_error, got {task.get('refund_error')}")

        # Assert: DB persisted
        row = db.execute("SELECT status FROM task_store WHERE task_id = ?", (task_id,)).fetchone()
        check(row is not None, "task not persisted to DB")
        check(row["status"] == "error", f"DB status={row['status']}, expected error")

        # Assert: SSE failed event was pushed
        failed_events = [e for e in collected_events if e.get("status") == "failed"]
        check(len(failed_events) >= 1, f"expected at least 1 failed SSE event, got {len(failed_events)}")

        # Assert: generation_history has a failed record
        hist = db.execute(
            "SELECT status FROM generation_history WHERE task_id = ?", (task_id,)
        ).fetchone()
        check(hist is not None, "no history record for failed task")
        check(hist["status"] == "failed", f"history status={hist['status']}, expected failed")

        # Cleanup: restore originals
        m.apimart_upload_image = orig_upload
        m.ensure_refund_once = orig_refund
        m.push_event = orig_push
        m.task_store.pop(task_id, None)

        if hasattr(database._local, "conn") and database._local.conn is not None:
            database._local.conn.close()
            database._local.conn = None

    print("refund failure terminal state regression tests passed")


if __name__ == "__main__":
    main()
