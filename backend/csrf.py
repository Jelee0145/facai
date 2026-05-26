"""CSRF 防护 — 用 JWT jti 作为 CSRF token"""
from fastapi import HTTPException, Request

CSRF_HEADER = "X-CSRF-Token"


async def verify_csrf(request: Request):
    """验证 X-CSRF-Token 与当前 JWT 的 jti 一致"""
    from security import verify_token

    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    else:
        token = request.cookies.get("access_token", "")

    if not token:
        raise HTTPException(status_code=401, detail="Missing auth token")

    csrf_token = request.headers.get(CSRF_HEADER, "")
    if not csrf_token:
        raise HTTPException(status_code=403, detail="Missing CSRF token")

    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid auth token")

    if csrf_token != payload.get("jti", ""):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")
