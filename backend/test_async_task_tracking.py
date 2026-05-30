"""Tests for _cleanup_active_task done-callback behavior."""
import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("API_AUTH_TOKEN", "test-token")

from database import init_db, get_db
import database
import main


def setup_db():
    database.DB_PATH = ":memory:"
    database._local = type(database._local)()
    init_db()


async def _success_coro():
    return "ok"


async def _fail_coro():
    raise ValueError("boom")


async def _cancel_coro():
    await asyncio.sleep(100)


def test_cleanup_on_success():
    main._active_tasks.add("t-success")
    loop = asyncio.new_event_loop()
    task = loop.create_task(_success_coro())
    loop.run_until_complete(task)
    main._cleanup_active_task("t-success", task)
    assert "t-success" not in main._active_tasks, "Should be removed from active tasks"
    loop.close()


def test_cleanup_on_failure():
    main._active_tasks.add("t-fail")
    main.task_store["t-fail"] = {"status": "generating", "user_id": 1, "charge_points": 10}
    loop = asyncio.new_event_loop()
    task = loop.create_task(_fail_coro())
    try:
        loop.run_until_complete(task)
    except ValueError:
        pass
    main._cleanup_active_task("t-fail", task)
    assert "t-fail" not in main._active_tasks
    assert main.task_store["t-fail"]["status"] == "error"
    loop.close()


def test_cleanup_on_cancel():
    main._active_tasks.add("t-cancel")
    loop = asyncio.new_event_loop()
    task = loop.create_task(_cancel_coro())
    loop.run_until_complete(asyncio.sleep(0))
    task.cancel()
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        pass
    main._cleanup_active_task("t-cancel", task)
    assert "t-cancel" not in main._active_tasks
    loop.close()


def test_cleanup_idempotent():
    """Calling cleanup twice should not raise."""
    main._active_tasks.add("t-idempotent")
    loop = asyncio.new_event_loop()
    task = loop.create_task(_success_coro())
    loop.run_until_complete(task)
    main._cleanup_active_task("t-idempotent", task)
    main._cleanup_active_task("t-idempotent", task)  # Second call
    assert "t-idempotent" not in main._active_tasks
    loop.close()


def test_cleanup_with_done_callback_integration():
    """Verify add_done_callback triggers cleanup automatically."""
    main._active_tasks.add("t-cb")
    loop = asyncio.new_event_loop()
    task = loop.create_task(_success_coro())
    task.add_done_callback(lambda t: main._cleanup_active_task("t-cb", t))
    loop.run_until_complete(task)
    # Give callback a chance to run
    loop.run_until_complete(asyncio.sleep(0))
    assert "t-cb" not in main._active_tasks, "Callback should have cleaned up"
    loop.close()


if __name__ == "__main__":
    setup_db()
    tests = [
        test_cleanup_on_success,
        test_cleanup_on_failure,
        test_cleanup_on_cancel,
        test_cleanup_idempotent,
        test_cleanup_with_done_callback_integration,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n  TOTAL: {len(tests)} | PASS: {passed} | FAIL: {failed}")
    sys.exit(1 if failed else 0)
