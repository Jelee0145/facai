"""Regression tests for generation refund idempotency."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    import database

    with tempfile.TemporaryDirectory() as tmp:
        if hasattr(database._local, "conn") and database._local.conn is not None:
            database._local.conn.close()
            database._local.conn = None

        database.DB_PATH = str(Path(tmp) / "refunds.db")
        importlib.reload(database)
        database.DB_PATH = str(Path(tmp) / "refunds.db")
        database.init_db()

        user_id = database.create_customer("refund-user", "unused-password-hash")
        db = database.get_db()
        db.execute("UPDATE user_wallets SET balance = 100 WHERE user_id = ?", (user_id,))
        db.commit()

        database.charge_generation(user_id, "task-1", 10, "test charge")
        first = database.ensure_refund_once({}, user_id, "task-1", 10, "first refund")
        second = database.ensure_refund_once({}, user_id, "task-1", 10, "second refund")

        wallet = database.get_wallet(user_id)
        refund_count = db.execute(
            "SELECT COUNT(*) AS cnt FROM user_ledger WHERE type = 'refund' AND reference_id = ?",
            ("task-1",),
        ).fetchone()["cnt"]

        check(first["status"] == "refunded", f"first refund status was {first}")
        check(second["status"] == "already_refunded", f"second refund status was {second}")
        check(refund_count == 1, f"expected one refund ledger, got {refund_count}")
        check(wallet["balance"] == 100, f"expected restored balance 100, got {wallet['balance']}")

        # Test unlimited user: refund should be skipped, no ledger entry
        uid_unlimited = database.create_customer("unlimited-user", "unused-hash")
        db.execute("UPDATE users SET is_unlimited = 1 WHERE id = ?", (uid_unlimited,))
        db.commit()

        database.charge_generation(uid_unlimited, "task-ul-1", 10, "unlimited charge")
        ul_result = database.ensure_refund_once({}, uid_unlimited, "task-ul-1", 10, "unlimited refund")
        check(ul_result["status"] == "skipped_unlimited", f"unlimited refund status was {ul_result}")
        ul_refund_count = db.execute(
            "SELECT COUNT(*) AS cnt FROM user_ledger WHERE type = 'refund' AND reference_id = ?",
            ("task-ul-1",),
        ).fetchone()["cnt"]
        check(ul_refund_count == 0, f"expected 0 refund ledger for unlimited, got {ul_refund_count}")
        ul_wallet = database.get_wallet(uid_unlimited)
        check(ul_wallet["balance"] == 999999999, f"expected unlimited balance 999999999, got {ul_wallet['balance']}")

        if hasattr(database._local, "conn") and database._local.conn is not None:
            database._local.conn.close()
            database._local.conn = None

    print("refund idempotency regression tests passed")


if __name__ == "__main__":
    main()
