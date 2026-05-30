"""
安全模块 — JWT 认证 + bcrypt 加密 + 防暴力破解
"""

import os
import re
import sys
import uuid
import logging
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException, Request
from database import get_user, record_login_attempt, record_customer_login_attempt, get_customer_by_username, get_customer_by_id, get_customer_login_lock

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    print("[SECURITY] CRITICAL: JWT_SECRET environment variable is not set!")
    print("[SECURITY] Generate one: python -c \"import secrets; print(secrets.token_hex(32))\"")
    print("[SECURITY] Set it in backend/.env: JWT_SECRET=<the generated value>")
    sys.exit(1)
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 1
JWT_EXPIRE_MINUTES = TOKEN_EXPIRE_DAYS * 24 * 60
JWT_REFRESH_MINUTES = 7 * 24 * 60  # 刷新 token 有效期 7 天
BCRYPT_ROUNDS = 12
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15

logger = logging.getLogger("ecommerce-gen.security")


def validate_password_strength(password: str) -> None:
    """Enforce password policy: mixed case, digit, special char."""
    if not isinstance(password, str):
        raise ValueError("密码格式无效")
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"密码长度不能少于 {PASSWORD_MIN_LENGTH} 位")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"密码长度不能超过 {PASSWORD_MAX_LENGTH} 位")
    if not re.search(r"[a-z]", password):
        raise ValueError("密码必须包含小写字母")
    if not re.search(r"[A-Z]", password):
        raise ValueError("密码必须包含大写字母")
    if not re.search(r"[0-9]", password):
        raise ValueError("密码必须包含数字")
    if not re.search(r"[^a-zA-Z0-9]", password):
        raise ValueError("密码必须包含特殊字符")



def hash_password(password: str) -> str:
    """bcrypt 加密"""
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def is_valid_password_hash(password_hash: str) -> bool:
    """Check whether a string is a parseable bcrypt hash."""
    if not isinstance(password_hash, str):
        return False
    if not password_hash.startswith(("$2a$", "$2b$", "$2y$")):
        return False
    try:
        bcrypt.checkpw(b"probe", password_hash.encode("utf-8"))
        return True
    except (ValueError, TypeError):
        return False


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码 — bcrypt 校验，坏 hash 返回 False 而非抛异常"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_token(username: str, role: str, expire_minutes: int = JWT_EXPIRE_MINUTES) -> str:
    _now = datetime.now(timezone.utc)
    payload = {
        "jti": str(uuid.uuid4()),
        "sub": username,
        "role": role,
        "iat": _now.replace(tzinfo=None),
        "exp": (_now + timedelta(minutes=expire_minutes)).replace(tzinfo=None),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_customer_token(user_id: int, username: str, expire_minutes: int = JWT_EXPIRE_MINUTES) -> str:
    _now = datetime.now(timezone.utc)
    payload = {
        "jti": str(uuid.uuid4()),
        "sub": str(user_id),
        "username": username,
        "role": "user",
        "token_type": "customer",
        "iat": _now.replace(tzinfo=None),
        "exp": (_now + timedelta(minutes=expire_minutes)).replace(tzinfo=None),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """验证 JWT token，同时检查 jti 吊销状态。
    Fail-closed: missing jti or DB error → token rejected."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
    jti = payload.get("jti")
    if not jti:
        # Tokens without jti are from before revocation support — reject
        logger.warning("Token missing jti claim, rejecting")
        return None
    try:
        from database import is_jti_revoked
        if is_jti_revoked(jti):
            return None
    except Exception as e:
        # Fail-closed: if we can't check revocation, reject the token
        logger.error(f"Failed to check jti revocation: {e}")
        return None
    return payload


async def authenticate(request: Request) -> dict:
    """从请求中提取并验证 JWT token
    支持 Authorization: Bearer 头 或 access_token cookie
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.cookies.get("access_token", "")

    if not token:
        raise HTTPException(status_code=401, detail="缺少认证令牌")

    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")

    return payload


async def authenticate_customer(request: Request) -> dict:
    token = request.cookies.get("user_access_token", "")
    auth_header = request.headers.get("Authorization", "")
    if not token and auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if not token:
        raise HTTPException(status_code=401, detail="请先登录")

    payload = verify_token(token)
    if not payload or payload.get("token_type") != "customer":
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    try:
        user_id = int(payload.get("sub", "0"))
    except ValueError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    user = get_customer_by_id(user_id)
    if not user or user.get("status") != "active":
        raise HTTPException(status_code=401, detail="账号不可用")

    return {
        "id": user_id,
        "username": user["username"],
        "phone": user.get("phone", ""),
        "email": user.get("email", ""),
        "is_unlimited": bool(user.get("is_unlimited")),
        "csrf_token": payload.get("jti", ""),
    }


async def login_customer(username: str, password: str) -> dict:
    # Check lock first (works for both existing and non-existing usernames)
    lock_until = get_customer_login_lock(username)
    if lock_until:
        lock_time = datetime.fromisoformat(lock_until)
        if lock_time > datetime.now():
            remaining = int((lock_time - datetime.now()).total_seconds() / 60)
            raise HTTPException(status_code=429, detail=f"账号已被锁定，请 {remaining} 分钟后重试")

    user = get_customer_by_username(username)
    if not user or user.get("status") != "active":
        record_customer_login_attempt(username, success=False)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    if not verify_password(password, user["password_hash"]):
        record_customer_login_attempt(username, success=False)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    record_customer_login_attempt(username, success=True)
    token = create_customer_token(int(user["id"]), user["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "phone": user.get("phone", ""),
            "email": user.get("email", ""),
            "is_unlimited": bool(user.get("is_unlimited")),
        },
        "expires_in": JWT_EXPIRE_MINUTES * 60,
    }


async def login(username: str, password: str) -> dict:
    """用户登录，返回 JWT token"""
    user = get_user(username)
    if not user or not user["is_active"]:
        record_login_attempt(username, False)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 检查锁定状态
    if user["locked_until"]:
        lock_time = datetime.fromisoformat(user["locked_until"])
        if lock_time > datetime.now():
            raise HTTPException(status_code=429, detail=f"账号已被锁定，请 {int((lock_time - datetime.now()).total_seconds() / 60)} 分钟后重试")

    if not verify_password(password, user["password_hash"]):
        record_login_attempt(username, False)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    record_login_attempt(username, True)
    token = create_token(username, user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "username": username,
            "role": user["role"],
        },
        "expires_in": JWT_EXPIRE_MINUTES * 60,
    }


def refresh_token(old_payload: dict) -> str:
    """使用旧 token（仍在有效期内）颁发新 token"""
    return create_token(old_payload["sub"], old_payload.get("role", "admin"))


def sanitize_input(value: str, max_length: int = 500) -> str:
    """输入消毒：strip + 长度限制"""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]
