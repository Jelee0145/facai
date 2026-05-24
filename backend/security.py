"""
安全模块 — JWT 认证 + bcrypt 加密 + 防暴力破解
"""

import os
import sys
import uuid
import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException, Request
from database import get_user, record_login_attempt

JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 1
JWT_EXPIRE_MINUTES = TOKEN_EXPIRE_DAYS * 24 * 60
JWT_REFRESH_MINUTES = 7 * 24 * 60  # 刷新 token 有效期 7 天
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15

if JWT_SECRET == "change-me-in-production":
    print("[SECURITY] CRITICAL: JWT_SECRET 环境变量未设置！")
    print("[SECURITY] 请执行: python -c \"import secrets; print(secrets.token_hex(32))\"")
    print("[SECURITY] 将输出值设为环境变量 JWT_SECRET")
    sys.exit(1)


def hash_password(password: str) -> str:
    """bcrypt 加密"""
    salt = bcrypt.gensalt(rounds=14)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


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


def verify_token(token: str) -> Optional[dict]:
    """验证 JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


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
