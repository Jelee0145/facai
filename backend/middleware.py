"""Rate limiting middleware."""
import os

import jwt
from fastapi import FastAPI, Request
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

JWT_ALGORITHM = "HS256"


def _decode_token(token: str) -> dict:
    secret = os.getenv("JWT_SECRET", "")
    if not token or not secret:
        return {}
    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError:
        return {}


def rate_limit_key(request: Request) -> str:
    admin_payload = _decode_token(request.cookies.get("access_token", ""))
    if admin_payload.get("role") == "admin":
        username = admin_payload.get("sub", "unknown")
        return f"admin:{username}"

    customer_payload = _decode_token(request.cookies.get("user_access_token", ""))
    if customer_payload.get("token_type") == "customer":
        user_id = customer_payload.get("sub", "unknown")
        return f"user:{user_id}"

    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key)


def init_rate_limiting(app: FastAPI):
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
