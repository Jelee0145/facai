"""Tests for JWT token verification, revocation, and fail-closed behavior."""
import os
import sys

# Ensure backend modules are importable
sys.path.insert(0, os.path.dirname(__file__))

# Set up env before importing security
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("API_AUTH_TOKEN", "test-token")

from security import (
    create_token,
    create_customer_token,
    verify_token,
    validate_password_strength,
    BCRYPT_ROUNDS,
    PASSWORD_MIN_LENGTH,
    PASSWORD_MAX_LENGTH,
)
from database import init_db, get_db, revoke_jti, is_jti_revoked


def setup_db():
    """Use a temporary in-memory DB for tests."""
    import database
    database.DB_PATH = ":memory:"
    database._local = type(database._local)()  # Reset thread-local
    init_db()


def test_normal_token_passes():
    token = create_token("admin", "admin")
    result = verify_token(token)
    assert result is not None, "Valid token should pass"
    assert result["sub"] == "admin"
    assert result["jti"] is not None


def test_customer_token_passes():
    token = create_customer_token(1, "testuser")
    result = verify_token(token)
    assert result is not None
    assert result["sub"] == "1"
    assert result["token_type"] == "customer"


def test_revoked_token_rejected():
    token = create_token("admin", "admin")
    payload = verify_token(token)
    assert payload is not None
    jti = payload["jti"]
    exp = payload.get("exp", "")
    revoke_jti(jti, str(exp))
    assert verify_token(token) is None, "Revoked token should be rejected"


def test_missing_jti_rejected():
    """Tokens without jti should be rejected (fail-closed)."""
    import jwt as pyjwt
    import os
    secret = os.environ.get("JWT_SECRET", "test")
    payload = {"sub": "admin", "role": "admin"}  # No jti
    token = pyjwt.encode(payload, secret, algorithm="HS256")
    result = verify_token(token)
    assert result is None, "Token without jti should be rejected"


def test_db_error_causes_rejection():
    """If DB query for revocation fails, token should be rejected (fail-closed)."""
    token = create_token("admin", "admin")
    payload = verify_token(token)
    assert payload is not None

    import database
    original = database.is_jti_revoked

    def raise_on_check(jti):
        raise RuntimeError("DB connection failed")

    database.is_jti_revoked = raise_on_check
    try:
        result = verify_token(token)
        assert result is None, "DB error should cause token rejection"
    finally:
        database.is_jti_revoked = original


def test_is_jti_revoked_false_for_unknown():
    result = is_jti_revoked("nonexistent-jti")
    assert result is False


def test_is_jti_revoked_true_after_revoke():
    jti = "test-jti-12345"
    assert is_jti_revoked(jti) is False
    revoke_jti(jti, "2099-01-01T00:00:00")
    assert is_jti_revoked(jti) is True


def test_revoke_jti_idempotent():
    jti = "test-jti-idempotent"
    revoke_jti(jti, "2099-01-01T00:00:00")
    revoke_jti(jti, "2099-01-01T00:00:00")  # Should not raise
    assert is_jti_revoked(jti) is True


# ---- Password policy tests ----

def test_password_min_length_constant():
    assert PASSWORD_MIN_LENGTH == 12, f"Expected min length 12, got {PASSWORD_MIN_LENGTH}"


def test_password_max_length_constant():
    assert PASSWORD_MAX_LENGTH == 128


def test_short_password_fails():
    try:
        validate_password_strength("Aa1!aaaa")  # 8 chars, below 12
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "12" in str(e)


def test_strong_password_passes():
    validate_password_strength("Aa1!aaaaaaaa")  # 12 chars


def test_too_long_password_fails():
    try:
        validate_password_strength("Aa1!" + "a" * 130)  # 134 chars
        assert False
    except ValueError as e:
        assert "128" in str(e)


def test_missing_uppercase_fails():
    try:
        validate_password_strength("aa1!aaaaaaaa")
        assert False
    except ValueError:
        pass


def test_missing_lowercase_fails():
    try:
        validate_password_strength("AA1!AAAAAAAA")
        assert False
    except ValueError:
        pass


def test_missing_digit_fails():
    try:
        validate_password_strength("AaX!aaaaaaaa")
        assert False
    except ValueError:
        pass


def test_missing_special_fails():
    try:
        validate_password_strength("Aa1Xaaaaaaaa")
        assert False
    except ValueError:
        pass


if __name__ == "__main__":
    setup_db()
    tests = [
        test_normal_token_passes,
        test_customer_token_passes,
        test_revoked_token_rejected,
        test_missing_jti_rejected,
        test_db_error_causes_rejection,
        test_is_jti_revoked_false_for_unknown,
        test_is_jti_revoked_true_after_revoke,
        test_revoke_jti_idempotent,
        test_password_min_length_constant,
        test_password_max_length_constant,
        test_short_password_fails,
        test_strong_password_passes,
        test_too_long_password_fails,
        test_missing_uppercase_fails,
        test_missing_lowercase_fails,
        test_missing_digit_fails,
        test_missing_special_fails,
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
