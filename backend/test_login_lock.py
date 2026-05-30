"""Unit tests for customer login lock on non-existing usernames."""

from __future__ import annotations

import importlib
import os
import tempfile
from datetime import datetime
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

        database.DB_PATH = str(Path(tmp) / "lock_test.db")
        importlib.reload(database)
        database.DB_PATH = str(Path(tmp) / "lock_test.db")
        database.init_db()

        # Non-existing user: 5 failed attempts should lock
        for i in range(5):
            database.record_customer_login_attempt("__missing_user__", False)

        lock = database.get_customer_login_lock("__missing_user__")
        check(lock is not None, "expected lock after 5 failures")
        lock_time = datetime.fromisoformat(lock)
        check(lock_time > datetime.now(), f"expected future lock time, got {lock}")

        # Success clears the lock
        database.record_customer_login_attempt("__missing_user__", True)
        lock_after = database.get_customer_login_lock("__missing_user__")
        check(lock_after is None, f"expected lock cleared after success, got {lock_after}")

        # Existing user: same behavior
        from security import hash_password
        user_id = database.create_customer("lock-test-user", hash_password("test123"))
        for i in range(5):
            database.record_customer_login_attempt("lock-test-user", False)

        lock2 = database.get_customer_login_lock("lock-test-user")
        check(lock2 is not None, "expected lock after 5 failures for real user")
        lock_time2 = datetime.fromisoformat(lock2)
        check(lock_time2 > datetime.now(), f"expected future lock time for real user, got {lock_time2}")

        if hasattr(database._local, "conn") and database._local.conn is not None:
            database._local.conn.close()
            database._local.conn = None

    print("login lock regression tests passed")


if __name__ == "__main__":
    main()
