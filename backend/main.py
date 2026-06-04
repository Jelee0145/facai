"""
FastAPI 图片生成后端
接管原 Next.js /api/generate 的完整流程：
上传图片 → 品类匹配 → prompt 构建 → apimart 批量生成 → 轮询 → 返回结果
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import secrets
import time
import os
import sys
import uuid
from typing import Literal, Optional
from fastapi import FastAPI, HTTPException, Request, Depends, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import httpx
import traceback
from dotenv import load_dotenv

# Fill blank secrets before loading .env into the process environment
from env_setup import auto_fill_env

auto_fill_env()
load_dotenv(override=True)

from prompts_v2 import (
    match_category,
    select_model,
    get_model_profile,
    generate_all_tasks,
    _normalize_tags,
    build_comparison_prompt,
    build_detail_prompt,
    PromptValidationError,
    COUNTRY_CONFIG,
    MODEL_STYLE_NAMES,
)
from key_manager import key_manager
from security import (
    authenticate,
    authenticate_customer,
    create_customer_token,
    hash_password,
    is_valid_password_hash,
    login,
    login_customer,
    sanitize_input,
    refresh_token,
    validate_password_strength,
    TOKEN_EXPIRE_DAYS,
    JWT_EXPIRE_MINUTES,
)
from middleware import init_rate_limiting
from csrf import verify_csrf
from sse import sse_stream, push_event
from middleware import limiter
from database import (
    get_all_keys, get_all_keys_masked, add_key as db_add_key,
    update_key as db_update_key,
    delete_key as db_delete_key, get_history, get_dashboard_stats,
    add_history, add_key, get_key_by_value,
    save_task_progress, load_pending_tasks, delete_old_tasks, init_db,
    get_config, set_config, get_all_configs,
    get_custom_types, add_custom_type, delete_custom_type,
    charge_generation, create_customer, create_order, get_active_keys, get_generation_cost_points,
    get_wallet, list_all_orders, list_credit_packages, list_user_history,
    list_user_ledger, list_user_orders, mark_order_paid,
    upsert_credit_package, delete_credit_package, get_user, create_user, ensure_refund_once,
    mask_api_key, update_admin_password,
    get_user_history_detail,
    list_all_users, admin_create_user, update_user_status, update_user_note, delete_user,
    submit_order_proof, reject_order, get_order_proof,
    reset_daily_usage,
)
from llm_provider import generate_model_prompts, generate_product_prompts, generate_metadata

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ecommerce-gen")

app = FastAPI(title="E-Commerce Image Generator", version="1.0.0")

init_rate_limiting(app)

API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1", "yes")

MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/avif"}

DATA_URL_PATTERN = re.compile(r"^data:(image/\w+);base64,(.+)$")


def ensure_api_key_available():
    if not get_active_keys():
        raise HTTPException(status_code=409, detail="没有可用的 API Key（可能因连续鉴权失败被自动禁用），请到后台检查 Key 状态或添加新 Key")


def _try_refund_generation(task_data: dict, user_id: int, task_id: str, points: int, reason: str) -> dict:
    """Attempt a refund; swallow exceptions so task can still reach terminal state."""
    try:
        return ensure_refund_once(task_data, user_id, task_id, points, reason)
    except Exception as err:
        logger.exception(f"[REFUND] Refund failed for task {task_id}: {err}")
        task_data["refund_status"] = "failed"
        task_data["refund_error"] = str(err)[:500]
        return {"status": "failed", "refunded": False, "points": points, "error": str(err)[:500]}


def validate_image_data(image_url: str):
    """验证图片数据 URL 的格式、MIME 类型和大小"""
    if image_url.startswith("http://") or image_url.startswith("https://"):
        return
    m = DATA_URL_PATTERN.match(image_url)
    if not m:
        raise HTTPException(status_code=400, detail="不支持的图片格式，仅支持 HTTP URL 或 data:image 格式")
    mime = m.group(1).lower()
    if mime not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(status_code=400, detail=f"不支持的图片 MIME 类型: {mime}，仅支持 JPEG/PNG/WebP/AVIF")
    base64_data = m.group(2)
    raw_size = len(base64_data) * 3 // 4
    if raw_size > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail=f"图片过大 ({raw_size / 1024 / 1024:.1f}MB)，最大允许 {MAX_IMAGE_SIZE / 1024 / 1024:.0f}MB")
    # Validate magic bytes match declared MIME
    try:
        raw_bytes = base64.b64decode(base64_data, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="图片 base64 数据无效")
    if len(raw_bytes) < 4:
        raise HTTPException(status_code=400, detail="图片数据过小，无法识别格式")
    # Check magic bytes
    header = raw_bytes[:8]
    valid_magic = False
    if header[:3] == b"\xff\xd8\xff":  # JPEG
        valid_magic = mime == "image/jpeg"
    elif header[:4] == b"\x89PNG":  # PNG
        valid_magic = mime == "image/png"
    elif header[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":  # WebP
        valid_magic = mime == "image/webp"
    elif header[:4] in (b"\x00\x00\x00\x1c", b"\x00\x00\x00\x20") or raw_bytes[4:8] == b"ftyp":  # AVIF/HEIF
        valid_magic = mime == "image/avif"
    if not valid_magic:
        raise HTTPException(status_code=400, detail="图片格式与声明的 MIME 类型不一致")


async def verify_api_auth(request: Request):
    """验证 API 内部认证令牌（保护生成端点不被外部直接调用）"""
    if not API_AUTH_TOKEN:
        raise HTTPException(status_code=503, detail="API auth is not configured")
    auth_header = request.headers.get("X-API-Auth", "")
    import hmac
    if not auth_header or not hmac.compare_digest(auth_header, API_AUTH_TOKEN):
        raise HTTPException(status_code=403, detail="Forbidden")
    return True


def _set_user_cookie(resp: JSONResponse, token: str, max_age: int = TOKEN_EXPIRE_DAYS * 24 * 3600):
    resp.set_cookie(
        key="user_access_token",
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=max_age,
        secure=COOKIE_SECURE,
    )


def _clear_user_cookie(resp: JSONResponse):
    resp.set_cookie(
        key="user_access_token",
        value="",
        httponly=True,
        samesite="lax",
        path="/",
        max_age=0,
        secure=COOKIE_SECURE,
    )


def _verify_user_csrf(request: Request, user: dict):
    if request.method.upper() in {"POST", "PUT", "DELETE"}:
        token = request.headers.get("X-CSRF-Token", "")
        if not token or token != user.get("csrf_token", ""):
            raise HTTPException(status_code=403, detail="CSRF token mismatch")


def _preview_images(urls: list[str]) -> str:
    visible = [u for u in urls if isinstance(u, str) and u and not u.startswith("data:")]
    return json.dumps(visible[:3], ensure_ascii=False)


def _history_description_snapshot(req: GenerateRequest) -> str:
    """Always use the user's original description, never product_type or LLM output."""
    return sanitize_input(req.description, 500)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常：过滤敏感路径信息"""
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, PromptValidationError):
        return JSONResponse(
            status_code=400,
            content={"detail": f"输入校验失败：{exc.message}", "field": exc.field},
        )
    msg = str(exc)
    msg = msg.replace(str(os.getcwd()).replace("\\", "/"), "[PROJECT_ROOT]")
    msg = msg.replace(str(os.getcwd()), "[PROJECT_ROOT]")
    msg = msg.replace("\\", "/")
    logger.error(f"{request.method} {request.url.path}: {msg}")
    logger.debug(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


@app.on_event("startup")
async def startup():
    """启动时恢复未完成任务，清理过期数据"""
    init_db()
    # Reset daily usage if it's a new day
    from datetime import date
    _last_reset = getattr(startup, "_last_reset_date", None)
    _today = date.today().isoformat()
    if _last_reset != _today:
        reset_daily_usage()
        startup._last_reset_date = _today
        print(f"[INIT] Daily usage reset for {_today}")
    # production safety: refuse to start without API_AUTH_TOKEN
    if os.getenv("NODE_ENV", "").lower() == "production" and not API_AUTH_TOKEN:
        print("[SECURITY] CRITICAL: NODE_ENV=production but API_AUTH_TOKEN is not set!")
        print("[SECURITY] Set API_AUTH_TOKEN in backend/.env and .env (frontend)")
        sys.exit(1)
    # Admin bootstrap
    WEAK_PASSWORDS = {"admin123", "password", "123456", "admin", "admin888", "test123"}
    _admin_pw = os.getenv("ADMIN_PASSWORD", "")
    _is_production = os.getenv("NODE_ENV", "").lower() in ("production", "prod")
    _admin_user = get_user("admin")
    if not _admin_user:
        # Admin does not exist — create if possible
        if not _admin_pw or (_is_production and _admin_pw.lower() in WEAK_PASSWORDS):
            if _is_production:
                print("[SECURITY] CRITICAL: Production requires a strong ADMIN_PASSWORD and admin account does not exist!")
                sys.exit(1)
            else:
                # Dev: auto-generate password and create admin
                _auto_pw = secrets.token_urlsafe(16)
                create_user("admin", hash_password(_auto_pw))
                print("=" * 60)
                print(f"[INIT] Admin account created with AUTO-GENERATED password:")
                print(f"  Username : admin")
                print(f"  Password : {_auto_pw}")
                print(f"[INIT] Please save this password! It will NOT be shown again.")
                print(f"[INIT] You can also set ADMIN_PASSWORD in .env and restart.")
                print("=" * 60)
        else:
            create_user("admin", hash_password(_admin_pw))
            print("[INIT] Admin account created from ADMIN_PASSWORD")
    else:
        # Admin exists — check if hash is valid
        if not is_valid_password_hash(_admin_user.get("password_hash", "")):
            # Bad hash: try to repair with ADMIN_PASSWORD
            _can_repair = _admin_pw and (not _is_production or _admin_pw.lower() not in WEAK_PASSWORDS)
            if _can_repair:
                update_admin_password("admin", hash_password(_admin_pw))
                print("[INIT] Admin password_hash was invalid — repaired from ADMIN_PASSWORD")
            else:
                msg = "[SECURITY] CRITICAL: Admin password_hash is invalid (not bcrypt). Login will fail. Set a strong ADMIN_PASSWORD and restart."
                if _is_production:
                    print(msg)
                    sys.exit(1)
                else:
                    print(msg)
    delete_old_tasks(hours=24)
    pending = load_pending_tasks()
    if pending:
        print(f"[RECOVERY] Restoring {len(pending)} pending tasks")
        # Tasks that were in-progress cannot be safely recovered
        for tid, task in pending.items():
            status = task.get("status", "submitting")
            task_store[tid] = task
            if status not in ("completed", "error", "failed"):
                # Mark as failed and refund
                uid = task.get("user_id")
                charge = task.get("charge_points", 0)
                if uid is not None and charge > 0:
                    _try_refund_generation(task, uid, tid, charge, "服务重启后无法恢复，自动退款")
                task["status"] = "error"
                task["error"] = "Task failed: server restarted while task was in progress"
                save_task_progress(tid, task)
                print(f"  [RECOVERY] Task {tid} marked as failed (was {status})")

    # 启动僵死任务回收协程
    async def reap_stale_tasks():
        """每60秒扫描一次，将僵死超过5分钟的task标记为error并退款"""
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                stale_ids = []
                for tid, task in list(task_store.items()):
                    if task.get("status") == "generating":
                        elapsed = now - task.get("start_time", now)
                        if elapsed > 300:  # 5 minutes
                            stale_ids.append(tid)
                for tid in stale_ids:
                    task = task_store[tid]
                    uid = task.get("user_id")
                    charge = task.get("charge_points", 0)
                    if uid is not None:
                        _try_refund_generation(task, uid, tid, charge, "僵死任务超时回收退款")
                    task["status"] = "error"
                    task["error"] = "Task timed out (no progress for >5 minutes)"
                    save_task_progress(tid, task)
                    push_event(tid, {"status": "failed", "error": task["error"]})
                    _active_tasks.discard(tid)
                if stale_ids:
                    logger.info(f"[REAPER] Marked {len(stale_ids)} stale task(s) as error (with refund if applicable)")
            except Exception as e:
                logger.error(f"[REAPER] Error in stale task reaper: {e}")
                await asyncio.sleep(10)  # 出错后短暂等待再继续

    asyncio.create_task(reap_stale_tasks())


CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:4524").split(",")
cors_origins = [o.strip() for o in CORS_ORIGINS]
if "*" in cors_origins and len(cors_origins) == 1:
    print("[WARN] CORS allow_origins=* 与 allow_credentials=True 冲突，浏览器将拒绝携带 Cookie 的请求")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Cookie"],
)

# Static file serving for payment proof uploads
os.makedirs(os.path.join(os.path.dirname(__file__), "uploads", "proofs"), exist_ok=True)
app.mount("/uploads", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "uploads")), name="uploads")

# ========== Apimart 配置 ==========
APIMART_BASE = "https://api.apimart.ai/v1"
MAX_CONCURRENT = 3  # 每次最多 3 个并发请求
APIMART_INITIAL_WAIT_SECONDS = int(os.getenv("APIMART_INITIAL_WAIT_SECONDS", "15"))
APIMART_POLL_INTERVAL_SECONDS = int(os.getenv("APIMART_POLL_INTERVAL_SECONDS", "4"))
APIMART_POLL_TIMEOUT_SECONDS = int(os.getenv("APIMART_POLL_TIMEOUT_SECONDS", "3600"))
COST_PER_IMAGE_USD = float(os.getenv("COST_PER_IMAGE_USD", "0.006"))


# ========== 请求/响应模型 ==========
class GenerateRequest(BaseModel):
    image_url: str
    product_type: str = Field(default="", max_length=200)
    country: str = Field(
        default="japan",
        pattern=r"^(japan|korea|usa|thailand|vietnam|malaysia|philippines|indonesia|china)$",
    )
    model: str = "general"
    model_name: str = Field(default="通用模型", max_length=50)
    model_desc: str = Field(default="综合效果好", max_length=200)
    generate_type: str = Field(default="all", pattern=r"^(all|comparison|detail|test)$")
    style_index: int = Field(default=0, ge=0, le=10)
    prompt_size: str = Field(default="auto", pattern=r"^(auto|1:1|4:3|3:4|16:9|9:16)$")
    prompt_resolution: str = Field(default="1k", pattern=r"^(1k|2k|4k)$")
    model_image_count: int = Field(default=4, ge=0, le=9)
    charge_points: Optional[int] = Field(default=None, ge=1, le=10)
    description: str = Field(default="", max_length=500)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=100)


class UserRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=12, max_length=128)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=120)


class CreateOrderRequest(BaseModel):
    package_id: int = Field(gt=0)


class CreditPackageRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    price_fen: int = Field(ge=0)
    points: int = Field(gt=0)
    bonus_points: int = Field(default=0, ge=0)
    status: str = Field(default="active", pattern=r"^(active|inactive)$")
    sort_order: int = Field(default=100, ge=0)


class CreateCustomTypeRequest(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    category: str = Field(default="自定义", max_length=50)


class CreateApiKeyRequest(BaseModel):
    key_value: str = Field(min_length=1, max_length=500)
    name: str = Field(default="", max_length=100)
    daily_limit: int = Field(default=200, ge=1, le=10000)


class AdminCreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=1, max_length=128)
    phone: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=500)
    is_unlimited: bool = Field(default=False)


class AdminChangePasswordRequest(BaseModel):
    new_password: str = Field(min_length=1, max_length=128)


class AdminUserStatusRequest(BaseModel):
    status: Literal["active", "frozen"]


class AdminUserNoteRequest(BaseModel):
    note: str = Field(default="", max_length=500)


# ========== 进度存储 ==========
task_store: dict[str, dict] = {}
_active_tasks: set[str] = set()  # Track running background tasks

MAIN_IMAGE_COUNT = 9
AUX_IMAGE_COUNT = 2
TOTAL_GENERATION_IMAGES = MAIN_IMAGE_COUNT + AUX_IMAGE_COUNT

IMAGE_NAMES = [
    "主图1", "主图2", "主图3", "主图4", "主图5",
    "主图6", "主图7", "主图8", "主图9",
    "局部放大图", "白底对比图",
]


def init_progress(total: int, creator_ip: str = "") -> str:
    """创建进度追踪，返回 task_group_id"""
    tid = str(uuid.uuid4())
    task_store[tid] = {
        "status": "submitting",
        "total": total,
        "completed": 0,
        "start_time": time.time(),
        "creator_ip": creator_ip,
        "images": [
            {"index": i, "status": "pending", "url": None, "name": IMAGE_NAMES[i] if i < len(IMAGE_NAMES) else f"图片{i+1}"}
            for i in range(total)
        ],
        "error": None,
        "result": None,
    }
    save_task_progress(tid, task_store[tid])
    return tid


def get_task_for_request(task_id: str, request: Request, user: dict) -> dict:
    p = task_store.get(task_id)
    if not p:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    task_user_id = p.get("user_id")
    if task_user_id is None or int(task_user_id) != int(user["id"]):
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return p


def build_progress_event(p: dict) -> dict:
    status = p.get("status", "generating")
    event_status = "failed" if status == "error" else status
    event = {
        "status": event_status,
        "total": p.get("total", TOTAL_GENERATION_IMAGES),
        "completed": p.get("completed", 0),
        "images": [
            {"index": img["index"], "status": img["status"], "url": img.get("url"), "name": img["name"]}
            for img in p.get("images", [])
        ],
    }
    if p.get("result") is not None:
        event["result"] = p["result"]
    if p.get("error"):
        event["error"] = p["error"]
    if p.get("partial") is not None:
        event["partial"] = p.get("partial")
        event["success_count"] = p.get("success_count", p.get("completed", 0))
        event["total_count"] = p.get("total", TOTAL_GENERATION_IMAGES)
    return event


# ========== Apimart API 工具函数 ==========
def _apimart_error_message(resp: httpx.Response, fallback: str) -> str:
    try:
        error_body = resp.json() if resp.text else {}
    except Exception:
        return fallback
    if isinstance(error_body, dict):
        error = error_body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if error_body.get("message"):
            return str(error_body["message"])
        if error_body.get("detail"):
            return str(error_body["detail"])
    return fallback


async def _apimart_request(
    url: str,
    method: str = "POST",
    json_body: dict = None,
    retries: int = 3,
    api_key: str | None = None,
    rotate_on_auth_failure: bool = True,
    count_success: bool = True,
    count_auth_failure: bool = True,
    return_key: bool = False,
):
    """带重试和多 Key 支持的 apimart API 请求。

    生成任务提交会轮询可用 Key；任务状态查询必须传入创建该 task 的 Key，
    避免用 B Key 查询 A Key 创建的 task 后把有效 Key 误判为鉴权失败。
    """
    selected_key = api_key
    if not selected_key:
        key_row = key_manager.get_active_key()
        if not key_row:
            raise HTTPException(status_code=409, detail="所有 API Key 均已失效，请到后台检查或添加新 Key")
        selected_key = key_row["key_value"]

    auth_failed_keys: set[str] = set()

    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                headers = {
                    "Authorization": f"Bearer {selected_key}",
                    "Content-Type": "application/json",
                }
                if method == "POST":
                    resp = await client.post(url, headers=headers, json=json_body)
                else:
                    resp = await client.get(url, headers=headers)

                if resp.status_code == 200:
                    if count_success:
                        key_manager.mark_success(selected_key)
                    result = resp.json()
                    return (result, selected_key) if return_key else result

                # Only authentication/permission failures prove the key itself is bad.
                if resp.status_code in (401, 403):
                    first_auth_failure_for_key = selected_key not in auth_failed_keys
                    auth_failed_keys.add(selected_key)
                    if count_auth_failure and first_auth_failure_for_key:
                        key_manager.mark_failure(selected_key)
                    if rotate_on_auth_failure and not api_key:
                        new_key_value = None
                        for _ in range(max(len(get_active_keys()), 1)):
                            new_key = key_manager.get_active_key()
                            if new_key and new_key["key_value"] not in auth_failed_keys:
                                new_key_value = new_key["key_value"]
                                break
                        if new_key_value:
                            selected_key = new_key_value
                            print(f"  Key 失效，切换到: {selected_key[:15]}...")
                            continue
                        raise HTTPException(status_code=502, detail="所有 API Key 鉴权均失败，请到后台检查 Key 状态")
                    raise HTTPException(status_code=502, detail="Apimart 任务查询鉴权失败，已保护 API Key 不自动禁用")

                # Quota/payment failures should be surfaced, not counted as auth failure.
                if resp.status_code == 402:
                    raise HTTPException(status_code=402, detail="Apimart API Key 额度不足或账号未开通 (402)")

                raise HTTPException(
                    status_code=502,
                    detail=_apimart_error_message(resp, f"Apimart {resp.status_code}"),
                )
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError, httpx.TimeoutException) as e:
            if attempt < retries - 1:
                delay = 2 * (attempt + 1)
                print(f"  [重试 {attempt+1}/{retries-1}] 网络错误，{delay}s 后重试...")
                await asyncio.sleep(delay)
            else:
                raise HTTPException(status_code=502, detail="上游 API 网络连接失败，请稍后重试")


def _normalise_url_for_compare(url: str | None) -> str:
    if not isinstance(url, str):
        return ""
    return url.strip()


def _extract_result_urls(value) -> list[str]:
    urls: list[str] = []

    def collect(node):
        if isinstance(node, str):
            url = node.strip()
            if url.startswith(("http://", "https://")):
                urls.append(url)
            return
        if isinstance(node, list):
            for item in node:
                collect(item)
            return
        if isinstance(node, dict):
            for item in node.values():
                collect(item)

    collect(value)
    deduped: list[str] = []
    seen = set()
    for url in urls:
        if url not in seen:
            deduped.append(url)
            seen.add(url)
    return deduped


def _select_generated_url(urls: list[str], reference_url: str | None = None) -> str | None:
    reference = _normalise_url_for_compare(reference_url)
    if reference:
        for url in urls:
            if _normalise_url_for_compare(url) != reference:
                return url
        return None
    return urls[0] if urls else None


async def apimart_upload_image(image_url: str) -> str:
    """将 base64 图片上传到 apimart，返回 hosted URL (72h 有效)。
    如果已经是 HTTP URL，直接返回。"""
    if image_url.startswith("http://") or image_url.startswith("https://"):
        return image_url

    m = DATA_URL_PATTERN.match(image_url)
    if not m:
        raise HTTPException(status_code=400, detail="图片格式无效，需为 HTTP URL 或 data:image/*;base64 格式")

    mime = m.group(1)  # e.g. "image/jpeg"
    b64_data = m.group(2)
    ext = mime.split("/")[-1].replace("jpeg", "jpg")
    raw_bytes = base64.b64decode(b64_data)

    key_row = key_manager.get_active_key()
    if not key_row:
        raise HTTPException(status_code=409, detail="所有 API Key 均已失效")

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{APIMART_BASE}/uploads/images",
            headers={"Authorization": f"Bearer {key_row['key_value']}"},
            files={"file": (f"image.{ext}", raw_bytes, mime)},
        )

    if resp.status_code != 200:
        error_body = resp.json() if resp.text else {}
        msg = error_body.get("error", {}).get("message", f"Upload failed: {resp.status_code}")
        raise HTTPException(status_code=502, detail=f"图片上传失败: {msg}")

    uploaded_url = resp.json()["url"]
    print(f"  [UPLOAD] Image uploaded: {uploaded_url[:80]}...")
    return uploaded_url


async def apimart_generate(prompt: str, reference_url: str = None, size: str = "1:1", resolution: str = "1k") -> str:
    """提交任务 → 轮询 → 返回图片 URL"""
    # 提交
    body = {
        "model": "gpt-image-2",
        "prompt": prompt,
        "n": 1,
        "size": size,
        "resolution": resolution,
    }
    if reference_url:
        body["image_urls"] = [reference_url]

    result, task_api_key = await _apimart_request(
        f"{APIMART_BASE}/images/generations",
        "POST",
        body,
        return_key=True,
    )
    task_id = result["data"][0].get("task_id")
    if not task_id:
        raise HTTPException(status_code=502, detail="未返回 task_id")

    # 等待（文档建议 10-20s）
    await asyncio.sleep(APIMART_INITIAL_WAIT_SECONDS)

    # 轮询
    deadline = time.monotonic() + APIMART_POLL_TIMEOUT_SECONDS
    round_num = 0
    while time.monotonic() < deadline:
        round_num += 1
        qr = await _query_single_task(task_id, reference_url, task_api_key)
        if isinstance(qr, str) and qr != "failed":
            return qr
        if qr == "failed":
            raise HTTPException(status_code=502, detail="图片生成任务失败")
        if isinstance(qr, dict):
            print(f"  [轮询 #{round_num}] status={qr['status']}, progress={qr.get('progress', 0)}")
        await asyncio.sleep(APIMART_POLL_INTERVAL_SECONDS)

    raise HTTPException(status_code=502, detail=f"任务轮询超时（超过 {APIMART_POLL_TIMEOUT_SECONDS} 秒）")


async def apimart_batch_generate(
    tasks: list[dict],
    on_progress: Optional[callable] = None,
    on_heartbeat: Optional[callable] = None,
) -> list[str]:
    """
    批量生成：分批提交 → 统一等待 → 批量轮询
    tasks: [{prompt, reference_url, size, resolution}, ...]
    on_progress: 可选回调 (index, url) — 每完成一张图时调用
    on_heartbeat: 可选回调 (processing_count) — 长时间等待时发送心跳
    """
    total = len(tasks)
    print(f"\n[BATCH] apimart batch generate: submitting {total} tasks (concurrency {MAX_CONCURRENT})...")

    # Step 1: 分批提交
    submissions = []  # [(index, task_id, api_key)]
    for batch_start in range(0, total, MAX_CONCURRENT):
        batch = tasks[batch_start : batch_start + MAX_CONCURRENT]
        batch_futures = []
        for offset, task in enumerate(batch):
            i = batch_start + offset
            batch_futures.append(_submit_task(task, i, total))

        results = await asyncio.gather(*batch_futures, return_exceptions=True)
        for r in results:
            if isinstance(r, tuple):
                submissions.append(r)

    task_ids = [tid for _, tid, _ in submissions]
    task_map = {tid: idx for idx, tid, _ in submissions}
    task_api_keys = {tid: used_key for _, tid, used_key in submissions}
    task_api_keys_by_pos = {idx: used_key for idx, _, used_key in submissions}
    print(f"\n[PROGRESS] Submitted: {len(task_ids)}/{total}")

    if not task_ids:
        raise HTTPException(status_code=502, detail="图片生成任务提交失败")

    # Step 2: 等待（文档建议 10-20s）
    await asyncio.sleep(APIMART_INITIAL_WAIT_SECONDS)

    # Step 3: 批量轮询 — 后端持续保活，直到完成、上游终态失败或服务端总超时
    results = [None] * total
    deadline = time.monotonic() + APIMART_POLL_TIMEOUT_SECONDS
    round_num = 0

    while time.monotonic() < deadline:
        round_num += 1
        pending = [tid for tid in task_ids if results[task_map[tid]] is None]
        if not pending:
            break

        completed_this_round = 0
        active_processing = 0  # 统计仍在处理中的任务数
        fatal_error = None

        try:
            query_results = await asyncio.gather(
                *[
                    _query_single_task(
                        tid,
                        tasks[task_map[tid]].get("reference_url"),
                        task_api_keys.get(tid),
                    )
                    for tid in pending
                ],
                return_exceptions=True,
            )

            for tid, qr in zip(pending, query_results):
                idx = task_map.get(tid)
                if idx is None:
                    continue

                if isinstance(qr, str) and qr != "failed":
                    # 成功拿到 URL
                    results[idx] = qr
                    completed_this_round += 1
                    if on_progress:
                        on_progress(idx, qr)
                elif qr == "failed":
                    results[idx] = "FAILED"  # 使用哨兵值区分真正失败 vs 未轮询
                    completed_this_round += 1
                    if on_progress:
                        on_progress(idx, None)
                elif isinstance(qr, HTTPException):
                    fatal_error = qr
                    break
                elif isinstance(qr, dict):
                    active_processing += 1  # 任务仍在处理中
                # elif qr is None: 网络错误，继续等

        except Exception as e:
            print(f"  [轮询 #{round_num+1}] 批量查询出错: {e}")

        if fatal_error:
            print(f"  [FATAL] 致命错误，终止轮询: {fatal_error.detail}")
            raise fatal_error

        remaining = sum(1 for r in results if r is None)
        stalled_count = len(pending) - completed_this_round - active_processing
        if completed_this_round == 0 and on_heartbeat:
            on_heartbeat(active_processing, stalled_count)

        print(f"  [轮询 #{round_num}] +{completed_this_round} done, {active_processing} processing, {stalled_count} waiting, remaining {remaining}/{total}")

        if remaining == 0:
            break
        await asyncio.sleep(APIMART_POLL_INTERVAL_SECONDS)

    # 统计成功数量，全部失败则报错
    success_count = sum(1 for r in results if r is not None and r != "FAILED")
    if success_count == 0:
        pending_count = sum(1 for r in results if r is None)
        if pending_count > 0:
            raise HTTPException(status_code=502, detail=f"图片生成仍未完成，后端轮询超时（超过 {APIMART_POLL_TIMEOUT_SECONDS} 秒）")
        raise HTTPException(status_code=502, detail="图片生成全部失败，请稍后重试")

    # 构建最终结果：成功URL或空字符串
    final_results = [r if (r and r != "FAILED") else "" for r in results]

    # 只对被放弃的任务（None）推送失败事件，不重复推送已确认失败的（"FAILED"）
    abandoned_count = sum(1 for r in results if r is None)
    if abandoned_count > 0:
        print(f"  [WARN] {abandoned_count} task(s) abandoned (still processing when loop ended)")
        for i, r in enumerate(results):
            if r is None:
                if on_progress:
                    on_progress(i, None)
                print(f"  [WARN] Image {i} generation failed")
    return final_results, task_api_keys_by_pos


async def _submit_task(task: dict, index: int, total: int) -> tuple[int, str, str]:
    """提交单个任务，返回 (index, task_id)"""
    try:
        body = {
            "model": "gpt-image-2",
            "prompt": task["prompt"],
            "n": 1,
            "size": task.get("size", "auto"),
            "resolution": task.get("resolution", "1k"),
        }
        if task.get("reference_url"):
            body["image_urls"] = [task["reference_url"]]

        result, used_api_key = await _apimart_request(
            f"{APIMART_BASE}/images/generations",
            "POST",
            body,
            return_key=True,
        )
        tid = result["data"][0]["task_id"]
        print(f"  [{index+1}/{total}] 已提交: {tid}")
        return (index, tid, used_api_key)
    except Exception as e:
        print(f"  [{index+1}/{total}] 提交失败: {e}")
        raise


async def _query_single_task(task_id: str, reference_url: str | None = None, api_key: str | None = None):
    """查询单个任务状态。
    返回:
      str (URL) — completed，成功拿到图片
      "failed" — failed / cancelled
      dict {"status": ..., "progress": ...} — pending / processing，仍在进行中
      None — 网络错误，可重试
    异常:
      HTTPException — 不可重试的致命错误 (由 _apimart_request 抛出的 401/402/429 等)
    """
    try:
        task = await _apimart_request(
            f"{APIMART_BASE}/tasks/{task_id}",
            "GET",
            api_key=api_key,
            rotate_on_auth_failure=False,
            count_success=False,
            count_auth_failure=False,
        )
        data = task.get("data", {})
        status = data.get("status")

        if status == "completed":
            urls = _extract_result_urls(data.get("result", {}))
            generated_url = _select_generated_url(urls, reference_url)
            if generated_url:
                return generated_url
            if urls:
                print(f"  [WARN] Task {task_id} completed but only returned the reference image")
            else:
                print(f"  [WARN] Task {task_id} completed but result format unexpected")
            return "failed"

        if status in ("failed", "cancelled"):
            error_msg = data.get("error", {}).get("message", "未知错误")
            print(f"  [WARN] Task {task_id} {status}: {error_msg}")
            return "failed"

        # pending / processing — 还在进行中
        return {"status": status, "progress": data.get("progress", 0)}

    except HTTPException:
        # _apimart_request 已处理 401/402/429 等，直接向上抛
        raise
    except Exception as e:
        # 网络错误等，返回 None 让上层继续重试
        print(f"  [WARN] Query task {task_id} error: {e}")
        return None


def _build_tasks_detail(tasks: list[dict], urls: list[str] | None = None) -> str:
    """从任务列表和结果 URL 构建 tasks_detail JSON"""
    detail = []
    for i, task in enumerate(tasks):
        entry = {
            "index": i,
            "prompt": task.get("prompt", ""),
            "reference_url": task.get("reference_url", ""),
            "kind": task.get("kind", ""),
        }
        if urls and i < len(urls):
            entry["result_url"] = urls[i]
        detail.append(entry)
    return json.dumps(detail, ensure_ascii=False)


def _split_generation_urls(urls: list[str], model_image_count: int) -> dict:
    main_images = urls[:MAIN_IMAGE_COUNT]
    model_count = max(0, min(MAIN_IMAGE_COUNT, int(model_image_count)))
    detail_image = urls[MAIN_IMAGE_COUNT] if len(urls) > MAIN_IMAGE_COUNT else None
    comparison_image = urls[MAIN_IMAGE_COUNT + 1] if len(urls) > MAIN_IMAGE_COUNT + 1 else None
    return {
        "main_images": main_images,
        "model_images": main_images[:model_count],
        "product_images": main_images[model_count:],
        "detail_image": detail_image,
        "comparison_image": comparison_image,
        "model_image_count": model_count,
    }


# ========== API 端点 ==========

def _response_tags(gen_result: dict, country_config: dict) -> list[str]:
    return _normalize_tags(gen_result.get("tags") or country_config.get("hashtags", []))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/auth/register")
@limiter.limit("10/minute")
async def user_register(request: Request, req: UserRegisterRequest):
    username = sanitize_input(req.username, 50)
    phone = sanitize_input(req.phone, 30)
    email = sanitize_input(req.email, 120)
    try:
        validate_password_strength(req.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        user_id = create_customer(username, hash_password(req.password), phone=phone, email=email)
    except ValueError:
        raise HTTPException(status_code=409, detail="用户名已存在")
    token = create_customer_token(user_id, username)
    payload = {
        "user": {"id": user_id, "username": username, "phone": phone, "email": email, "is_unlimited": False},
        "csrf_token": "",
    }
    from security import verify_token
    token_payload = verify_token(token) or {}
    payload["csrf_token"] = token_payload.get("jti", "")
    payload["wallet"] = get_wallet(user_id)
    resp = JSONResponse(content=payload)
    _set_user_cookie(resp, token)
    return resp


@app.post("/auth/login")
@limiter.limit("10/minute")
async def user_login(request: Request, req: LoginRequest):
    result = await login_customer(sanitize_input(req.username, 50), req.password)
    from security import verify_token
    access_token = result.pop("access_token")
    token_payload = verify_token(access_token) or {}
    result["csrf_token"] = token_payload.get("jti", "")
    result["wallet"] = get_wallet(int(result["user"]["id"]))
    resp = JSONResponse(content=result)
    _set_user_cookie(resp, access_token)
    return resp


@app.post("/auth/logout")
async def user_logout(request: Request):
    user = await authenticate_customer(request)
    _verify_user_csrf(request, user)
    # Revoke the current token's jti
    token = request.cookies.get("user_access_token", "")
    if token:
        from security import verify_token
        from database import revoke_jti
        payload = verify_token(token)
        if payload and payload.get("jti"):
            exp = payload.get("exp", "")
            revoke_jti(payload["jti"], str(exp) if exp else "")
    resp = JSONResponse(content={"message": "logged out"})
    _clear_user_cookie(resp)
    return resp


@app.get("/auth/me")
async def user_me(request: Request):
    try:
        user = await authenticate_customer(request)
    except HTTPException as e:
        if e.status_code == 403 and "冻结" in str(e.detail):
            from security import verify_token
            from database import get_customer_by_id
            token = request.cookies.get("user_access_token", "")
            payload = verify_token(token)
            if payload:
                uid = int(payload.get("sub", "0"))
                frozen_user = get_customer_by_id(uid)
                if frozen_user:
                    return {
                        "user": {
                            "id": uid,
                            "username": frozen_user["username"],
                            "phone": frozen_user.get("phone", ""),
                            "email": frozen_user.get("email", ""),
                            "is_unlimited": bool(frozen_user.get("is_unlimited")),
                            "status": "frozen",
                        },
                        "wallet": get_wallet(uid),
                        "csrf_token": payload.get("jti", ""),
                        "generation_cost_points": get_generation_cost_points(),
                    }
        return {"user": None, "wallet": None, "csrf_token": "", "generation_cost_points": get_generation_cost_points()}
    return {
        "user": user,
        "wallet": get_wallet(int(user["id"])),
        "csrf_token": user.get("csrf_token", ""),
        "generation_cost_points": get_generation_cost_points(),
    }


@app.get("/user/wallet")
async def user_wallet(user: dict = Depends(authenticate_customer)):
    return {"wallet": get_wallet(int(user["id"])), "generation_cost_points": get_generation_cost_points()}


@app.get("/user/packages")
async def user_packages():
    return {"packages": list_credit_packages(include_inactive=False)}


@app.post("/user/orders")
@limiter.limit("20/minute")
async def user_create_order(request: Request, req: CreateOrderRequest, user: dict = Depends(authenticate_customer)):
    _verify_user_csrf(request, user)
    order_no = f"PAY{int(time.time())}{uuid.uuid4().hex[:8].upper()}"
    try:
        order = create_order(int(user["id"]), req.package_id, order_no)
    except ValueError:
        raise HTTPException(status_code=404, detail="套餐不存在或已下架")
    return {"order": order, "payment": {"provider": "manual", "status": "pending"}}


@app.get("/user/orders")
async def user_orders(user: dict = Depends(authenticate_customer)):
    return {"orders": list_user_orders(int(user["id"]))}


PROOF_MAX_SIZE = 5 * 1024 * 1024  # 5MB
PROOF_ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp"}


@app.post("/user/orders/{order_no}/submit-proof")
@limiter.limit("10/minute")
async def user_submit_proof(
    request: Request,
    order_no: str,
    user: dict = Depends(authenticate_customer),
    payment_remark: str = Form(""),
    proof_image: Optional[UploadFile] = File(None),
):
    _verify_user_csrf(request, user)
    safe_order_no = sanitize_input(order_no, 40)
    saved_path = ""
    if proof_image:
        if proof_image.content_type not in PROOF_ALLOWED_MIMES:
            raise HTTPException(status_code=400, detail="仅支持 JPG/PNG/WebP 格式图片")
        content = await proof_image.read()
        if len(content) > PROOF_MAX_SIZE:
            raise HTTPException(status_code=400, detail="图片大小不能超过 5MB")
        proofs_dir = os.path.join(os.path.dirname(__file__), "uploads", "proofs")
        os.makedirs(proofs_dir, exist_ok=True)
        raw_ext = proof_image.filename.rsplit(".", 1)[-1].lower() if proof_image.filename and "." in proof_image.filename else ""
        ext = raw_ext if raw_ext in ("jpg", "jpeg", "png", "webp") else "png"
        filename = f"{safe_order_no}_{int(time.time())}.{ext}"
        file_path = os.path.join(proofs_dir, filename)
        with open(file_path, "wb") as f:
            f.write(content)
        saved_path = f"/uploads/proofs/{filename}"
    if not payment_remark.strip() and not saved_path:
        raise HTTPException(status_code=400, detail="请至少填写付款备注或上传截图")
    try:
        order = submit_order_proof(safe_order_no, int(user["id"]), payment_remark.strip(), saved_path)
    except ValueError as e:
        if str(e) == "order_not_found":
            raise HTTPException(status_code=404, detail="订单不存在")
        if str(e) == "order_not_submittable":
            raise HTTPException(status_code=400, detail="订单当前状态不可提交凭证")
        raise
    return {"order": order}


@app.get("/user/ledger")
async def user_ledger(user: dict = Depends(authenticate_customer)):
    return {"items": list_user_ledger(int(user["id"]))}


@app.get("/user/history")
async def user_history(user: dict = Depends(authenticate_customer)):
    return {"items": list_user_history(int(user["id"]))}


@app.get("/user/history/{history_id}")
async def user_history_detail(history_id: int, user: dict = Depends(authenticate_customer)):
    item = get_user_history_detail(int(user["id"]), history_id)
    if not item:
        raise HTTPException(status_code=404, detail="记录不存在")
    return {"item": item}


@app.post("/api/generate")
@limiter.limit("10/minute")
async def generate_images(
    request: Request,
    req: GenerateRequest,
    _=Depends(verify_api_auth),
    user: dict = Depends(authenticate_customer),
):
    start = time.time()
    task_id = str(uuid.uuid4())
    user_id = int(user["id"])
    charge_points = req.charge_points if req.charge_points is not None else get_generation_cost_points()
    charge_state = {"charged": False, "refunded": False}

    try:
        _verify_user_csrf(request, user)
        if req.generate_type == "all":
            raise HTTPException(status_code=400, detail="完整生成请使用 /api/generate/async")
        validate_image_data(str(req.image_url))
        ensure_api_key_available()
        try:
            charge_generation(user_id, task_id, charge_points, f"生成任务 {task_id}")
            charge_state["charged"] = True
        except ValueError:
            raise HTTPException(status_code=402, detail="积分不足，请先充值")
        # 上传参考图到 apimart（base64 → hosted URL，72h 有效）
        hosted_image_url = await apimart_upload_image(str(req.image_url))
        # 1. 智能品类匹配
        category = match_category(req.product_type)
        model_code = select_model(req.model, category)
        model_profile = get_model_profile(model_code)
        country_config = COUNTRY_CONFIG.get(req.country, COUNTRY_CONFIG["usa"])

        print(f"[START] Processing: {req.product_type} -> {category['name']}")
        print(f"   [CATEGORY] {category['parent']} | [MODEL] {model_profile['name']} ({model_profile['tagline']})")
        print(f"   [MARKET] {country_config['name']} ({country_config['platform']}) | [SHOT] {category['shot_type']}")

        # LLM 智能生成 prompt（3 次并发请求，失败时静默降级）
        model_prompts = None
        product_prompts = None
        metadata = None
        llm_response_data = ""
        if get_config("llm_api_key"):
            try:
                common_args = dict(
                    image_url=hosted_image_url if hosted_image_url else None,
                    product_type=req.product_type,
                    country_name=country_config["name"],
                    platform=country_config["platform"],
                    model_name=req.model_name,
                    model_tagline=req.model_desc,
                    user_description=req.description,
                )
                # 并发 3 次 LLM 请求
                results = await asyncio.gather(
                    generate_model_prompts(count=req.model_image_count, **common_args),
                    generate_product_prompts(count=9 - req.model_image_count, **common_args),
                    generate_metadata(
                        product_type=req.product_type,
                        country_name=country_config["name"],
                        platform=country_config["platform"],
                        user_description=req.description,
                    ),
                    return_exceptions=True,
                )
                if isinstance(results[0], list):
                    model_prompts = results[0]
                if isinstance(results[1], list):
                    product_prompts = results[1]
                if isinstance(results[2], dict):
                    metadata = results[2]
                llm_response_data = json.dumps({
                    "model_prompts": model_prompts,
                    "product_prompts": product_prompts,
                    "metadata": metadata,
                }, ensure_ascii=False)
                print(f"  [LLM] Prompts generated: {len(model_prompts or [])} model + {len(product_prompts or [])} product + metadata={'yes' if metadata else 'no'}")
            except Exception as e:
                print(f"  [WARN] LLM prompt generation failed (downgrading): {e}")

        # 2. 单图生成模式
        if req.generate_type == "comparison":
            prompt = build_comparison_prompt(req.product_type, category)
            print("[COMPARISON] Generating comparison image...")
            url = await apimart_generate(prompt, hosted_image_url, req.prompt_size, req.prompt_resolution)
            add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                        country=sanitize_input(req.country, 20), model=model_code, status="completed",
                        elapsed_seconds=round(time.time() - start, 1), charge_points=charge_points,
                        description_snapshot=_history_description_snapshot(req),
                        preview_images_json=_preview_images([url]))
            return {"success": True, "data": {"comparisonImage": url}}

        if req.generate_type == "detail":
            prompt = build_detail_prompt(req.product_type, category)
            print("[DETAIL] Generating detail image...")
            url = await apimart_generate(prompt, hosted_image_url, req.prompt_size, req.prompt_resolution)
            add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                        country=sanitize_input(req.country, 20), model=model_code, status="completed",
                        elapsed_seconds=round(time.time() - start, 1), charge_points=charge_points,
                        description_snapshot=_history_description_snapshot(req),
                        preview_images_json=_preview_images([url]))
            return {"success": True, "data": {"detailImage": url}}

        if req.generate_type == "test":
            idx = max(0, min(req.style_index, 10))
            print(f"[TEST] Test mode: generating image {idx+1}/11...")
            gen_result = generate_all_tasks(
                req.product_type, hosted_image_url, req.country, req.model,
                req.prompt_size, req.prompt_resolution,
                category=category, country_config=country_config,
                model_code=model_code, model_profile=model_profile,
                model_prompts=model_prompts, product_prompts=product_prompts,
                metadata=metadata,
                model_image_count=req.model_image_count,
            )
            url = await apimart_generate(
                gen_result["tasks"][idx]["prompt"],
                gen_result["tasks"][idx]["reference_url"],
                req.prompt_size, req.prompt_resolution,
            )
            model_profile = gen_result["model_profile"]
            model_styles = MODEL_STYLE_NAMES
            tags = _response_tags(gen_result, country_config)
            tasks_detail = _build_tasks_detail(gen_result["tasks"], [url])
            add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                        country=sanitize_input(req.country, 20), model=model_code, status="completed",
                        elapsed_seconds=round(time.time() - start, 1),
                        llm_request="", llm_response=llm_response_data,
                        tasks_detail=tasks_detail, charge_points=charge_points,
                        description_snapshot=_history_description_snapshot(req),
                        preview_images_json=_preview_images([url]),
                        titles_json=json.dumps(gen_result.get("titles", []), ensure_ascii=False),
                        tags_json=json.dumps(tags, ensure_ascii=False),
                        target_audience=gen_result.get("target_audience", ""),
                        all_images_json=json.dumps([url], ensure_ascii=False))
            return {
                "success": True,
                "data": {
                    "modelImages": [url],
                    "modelStyles": [model_styles[idx]],
                    "originalImage": hosted_image_url,
                    "category": gen_result["category"],
                    "model": model_profile,
                    "country": gen_result["country_config"],
                    "titles": gen_result.get("titles", []),
                    "tags": tags,
                    "description": gen_result.get("description", ""),
                    "targetAudience": gen_result.get("target_audience", ""),
                },
            }

        # 3. 全量生成模式
        gen_result = generate_all_tasks(
            req.product_type, hosted_image_url, req.country, req.model,
            req.prompt_size, req.prompt_resolution,
            category=category, country_config=country_config,
            model_code=model_code, model_profile=model_profile,
            model_prompts=model_prompts, product_prompts=product_prompts,
            metadata=metadata,
            model_image_count=req.model_image_count,
        )

        urls, task_api_keys = await apimart_batch_generate(gen_result["tasks"])

        split = _split_generation_urls(urls, req.model_image_count)
        main_images = split["main_images"]
        model_images = split["model_images"]
        product_images = split["product_images"]
        detail_url = split["detail_image"]
        comparison_url = split["comparison_image"]
        tags = _response_tags(gen_result, country_config)

        elapsed = time.time() - start
        success_count = sum(1 for u in urls if u and not u.startswith("data:"))
        tasks_detail = _build_tasks_detail(gen_result["tasks"], urls)
        add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                    country=sanitize_input(req.country, 20), model=model_code, total_images=TOTAL_GENERATION_IMAGES,
                    success_count=success_count, status="completed", elapsed_seconds=round(elapsed, 1),
                    llm_request="", llm_response=llm_response_data,
                    tasks_detail=tasks_detail, charge_points=charge_points,
                    description_snapshot=_history_description_snapshot(req),
                    preview_images_json=_preview_images(model_images),
                    titles_json=json.dumps(gen_result.get("titles", []), ensure_ascii=False),
                    tags_json=json.dumps(tags, ensure_ascii=False),
                    target_audience=gen_result.get("target_audience", ""),
                    all_images_json=json.dumps(main_images, ensure_ascii=False))

        # ---- API Key 余额扣减 ----
        try:
            key_success_counts: dict[str, int] = {}
            for idx, url in enumerate(urls):
                if url and idx in task_api_keys:
                    kv = task_api_keys[idx]
                    key_success_counts[kv] = key_success_counts.get(kv, 0) + 1
            for key_value, img_count in key_success_counts.items():
                result = key_manager.deduct_balance(key_value, img_count)
                if result.get("clamped"):
                    print(f"[BALANCE] Key {result['key_id']} 余额耗尽，扣除 ${result['deducted']:.4f}，{img_count} 张")
                else:
                    print(f"[BALANCE] Key {result['key_id']} 扣除 ${result['deducted']:.4f}（{img_count} 张），余额 ${result['balance_after']:.4f}")
        except Exception as e:
            print(f"[BALANCE] 扣减失败（不影响生成）: {e}")

        print(f"[DONE] Completed! Elapsed {elapsed:.1f}s")

        return {
            "success": True,
            "data": {
            "originalImage": hosted_image_url,
            "mainImages": main_images,
            "modelImages": model_images,
            "productImages": product_images,
            "modelImageCount": split["model_image_count"],
            "modelStyles": MODEL_STYLE_NAMES,
            "comparisonImage": comparison_url,
            "detailImage": detail_url,
            # 品类信息
            "category": {
                "name": category["name"],
                "parent": category["parent"],
                "shotType": category["shot_type"],
            },
            # 模型信息
            "model": {
                "code": model_code,
                "name": model_profile["name"],
                "tagline": model_profile["tagline"],
            },
            # 市场信息
            "country": {
                "name": country_config["name"],
                "flag": country_config["flag"],
                "language": country_config["language"],
                "platform": country_config["platform"],
            },
            # 简化标题
            "titles": gen_result.get("titles", [
                f"{req.product_type} - {country_config['name']}爆款",
                "网红同款推荐",
                "限时热卖",
            ]),
            "description": gen_result.get("description", f"高品质{category['name']}，{category.get('detail_focus', '细节做工精良')}，适合{country_config['name']}市场"),
            "targetAudience": gen_result.get("target_audience", "18-35岁追求时尚的消费者"),
            "tags": tags,
        },
    }
    except HTTPException as e:
        print(f"[ERROR] Sync task {task_id} failed: {e.detail}")
        if charge_state["charged"]:
            _try_refund_generation(charge_state, user_id, task_id, charge_points, "生成失败自动退回")
        add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                    country=sanitize_input(req.country, 20), model="", status="failed", error_msg=str(e.detail)[:500],
                    description_snapshot=_history_description_snapshot(req))
        raise
    except Exception as e:
        print(f"[ERROR] Sync task {task_id} failed: {e}")
        if charge_state["charged"]:
            _try_refund_generation(charge_state, user_id, task_id, charge_points, "生成失败自动退回")
        add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                    country=sanitize_input(req.country, 20), model="", status="failed", error_msg=str(e)[:500],
                    description_snapshot=_history_description_snapshot(req))
        return JSONResponse(status_code=500, content={"success": False, "error": "Internal server error"})


# ========== 异步进度端点 ==========

def _cleanup_active_task(task_id: str, task: asyncio.Task):
    """Done-callback: always clean up _active_tasks, handle unexpected exceptions."""
    _active_tasks.discard(task_id)
    if task.cancelled():
        logger.warning(f"[TASK] Background task {task_id} was cancelled")
        return
    exc = task.exception()
    if exc is not None:
        logger.error(f"[TASK] Background task {task_id} raised: {exc}")
        # If task_store still shows non-terminal state, force terminal + refund
        p = task_store.get(task_id)
        if p and p.get("status") not in ("completed", "error", "failed"):
            uid = p.get("user_id")
            charge = p.get("charge_points", 0)
            if uid is not None and charge > 0:
                _try_refund_generation(p, uid, task_id, charge, "任务异常逃逸自动退款")
            p["status"] = "error"
            p["error"] = f"Task failed with unexpected error: {exc}"
            save_task_progress(task_id, p)
            push_event(task_id, {"status": "failed", "error": p["error"]})


async def _run_generation_background(task_id: str, req: GenerateRequest, user_id: int, charge_points: int):
    """后台执行完整的图片生成流程，并更新进度"""
    try:
        progress = task_store[task_id]
        progress["status"] = "submitting"
        push_event(task_id, {"status": "submitting", "total": progress["total"], "completed": 0})

        # 上传参考图到 apimart（base64 → hosted URL，72h 有效）
        hosted_image_url = await apimart_upload_image(req.image_url)

        # 品类匹配
        category = match_category(req.product_type)
        model_code = select_model(req.model, category)
        country_config = COUNTRY_CONFIG.get(req.country, COUNTRY_CONFIG["usa"])
        model_profile = get_model_profile(model_code)

        # LLM 智能生成 prompt（3 次并发请求，失败时静默降级）
        model_prompts = None
        product_prompts = None
        metadata = None
        llm_response_data = ""
        if get_config("llm_api_key"):
            try:
                common_args = dict(
                    image_url=hosted_image_url if hosted_image_url else None,
                    product_type=req.product_type,
                    country_name=country_config["name"],
                    platform=country_config["platform"],
                    model_name=req.model_name,
                    model_tagline=req.model_desc,
                    user_description=req.description,
                )
                results = await asyncio.gather(
                    generate_model_prompts(count=req.model_image_count, **common_args),
                    generate_product_prompts(count=9 - req.model_image_count, **common_args),
                    generate_metadata(
                        product_type=req.product_type,
                        country_name=country_config["name"],
                        platform=country_config["platform"],
                        user_description=req.description,
                    ),
                    return_exceptions=True,
                )
                if isinstance(results[0], list):
                    model_prompts = results[0]
                if isinstance(results[1], list):
                    product_prompts = results[1]
                if isinstance(results[2], dict):
                    metadata = results[2]
                llm_response_data = json.dumps({
                    "model_prompts": model_prompts,
                    "product_prompts": product_prompts,
                    "metadata": metadata,
                }, ensure_ascii=False)
                print(f"  [LLM] Prompts generated: {len(model_prompts or [])} model + {len(product_prompts or [])} product + metadata={'yes' if metadata else 'no'}")
            except Exception as e:
                print(f"  [WARN] LLM prompt generation failed (downgrading): {e}")

        # 生成任务
        gen_result = generate_all_tasks(
            req.product_type, hosted_image_url,
            req.country, req.model,
            req.prompt_size, req.prompt_resolution,
            category=category,
            country_config=country_config,
            model_code=model_code,
            model_profile=model_profile,
            model_prompts=model_prompts,
            product_prompts=product_prompts,
            metadata=metadata,
            model_image_count=req.model_image_count,
        )

        def on_progress(index: int, url: Optional[str]):
            """每完成一张图时更新进度"""
            p = task_store.get(task_id)
            if not p:
                return
            img = p["images"][index]
            if url:
                img["status"] = "completed"
                img["url"] = url
                p["completed"] += 1
            else:
                img["status"] = "failed"
            p["status"] = "generating"
            save_task_progress(task_id, p)
            push_event(task_id, {
                "status": "generating",
                "total": p["total"],
                "completed": p["completed"],
                "images": [
                    {"index": img["index"], "status": img["status"], "url": img.get("url"), "name": img["name"]}
                    for img in p["images"]
                ],
            })

        def on_heartbeat(processing_count: int, waiting_count: int = 0):
            """长时间等待时发送心跳，保持SSE连接活跃"""
            p = task_store.get(task_id)
            if p:
                push_event(task_id, {
                    "status": "generating",
                    "total": p["total"],
                    "completed": p["completed"],
                    "heartbeat": True,
                    "processing_count": processing_count,
                    "waiting_count": waiting_count,
                })

        progress["status"] = "generating"
        save_task_progress(task_id, progress)
        push_event(task_id, {"status": "generating", "total": progress["total"], "completed": 0})

        # 批量生成
        urls, task_api_keys = await apimart_batch_generate(
            gen_result["tasks"], on_progress, on_heartbeat
        )

        # 构建结果
        split = _split_generation_urls(urls, req.model_image_count)
        main_images = split["main_images"]
        model_images = split["model_images"]
        product_images = split["product_images"]
        detail_url = split["detail_image"]
        comparison_url = split["comparison_image"]
        tags = _response_tags(gen_result, country_config)

        # 检测是否为部分完成
        success_count = sum(1 for u in urls if u)  # 非空字符串数量
        total_count = len(urls)
        is_partial = success_count < total_count

        model_profile = get_model_profile(model_code)

        progress["result"] = {
            "success": True,
            "data": {
                "originalImage": hosted_image_url,
                "mainImages": main_images,
                "modelImages": model_images,
                "productImages": product_images,
                "modelImageCount": split["model_image_count"],
                "modelStyles": MODEL_STYLE_NAMES,
                "comparisonImage": comparison_url,
                "detailImage": detail_url,
                "category": {"name": category["name"], "parent": category["parent"], "shotType": category["shot_type"]},
                "model": {"code": model_code, "name": model_profile["name"], "tagline": model_profile["tagline"]},
                "country": {"name": country_config["name"], "flag": country_config["flag"], "platform": country_config["platform"]},
                "titles": gen_result.get("titles", [f"{req.product_type} - {country_config['name']}爆款", "网红同款推荐", "限时热卖"]),
                "description": gen_result.get("description", f"高品质{category['name']}，适合{country_config['name']}市场"),
                "targetAudience": gen_result.get("target_audience", "18-35岁追求时尚的消费者"),
                "tags": tags,
            },
        }
        progress["status"] = "completed"
        if is_partial:
            progress["partial"] = True
            progress["success_count"] = success_count
            progress["failed_count"] = total_count - success_count
            print(f"[PARTIAL] Background task {task_id} completed with {success_count}/{total_count} images")
        else:
            progress["partial"] = False
        save_task_progress(task_id, progress)
        push_event(task_id, {
            "status": "completed",
            "result": progress["result"],
            "partial": is_partial,
            "success_count": success_count,
            "total_count": total_count,
        })
        _active_tasks.discard(task_id)
        print(f"[DONE] Background task {task_id} completed")

        # 写入历史记录
        tasks_detail_json = _build_tasks_detail(gen_result["tasks"], urls)
        add_history(
            task_id=task_id,
            api_key_id=None,
            user_id=user_id,
            product_type=sanitize_input(req.product_type, 50),
            country=sanitize_input(req.country, 20),
            model=model_code,
            prompt_size=req.prompt_size,
            prompt_resolution=req.prompt_resolution,
            total_images=TOTAL_GENERATION_IMAGES,
            success_count=progress["completed"],
            status="completed",
            elapsed_seconds=round(time.time() - progress["start_time"], 1),
            llm_request="",
            llm_response=llm_response_data,
            tasks_detail=tasks_detail_json,
            charge_points=charge_points,
            description_snapshot=_history_description_snapshot(req),
            preview_images_json=_preview_images(model_images),
            titles_json=json.dumps(gen_result.get("titles", []), ensure_ascii=False),
            tags_json=json.dumps(tags, ensure_ascii=False),
            target_audience=gen_result.get("target_audience", ""),
            all_images_json=json.dumps(main_images, ensure_ascii=False),
        )

        # ---- API Key 余额扣减 ----
        try:
            key_success_counts: dict[str, int] = {}
            for idx, url in enumerate(urls):
                if url and idx in task_api_keys:
                    kv = task_api_keys[idx]
                    key_success_counts[kv] = key_success_counts.get(kv, 0) + 1
            for key_value, img_count in key_success_counts.items():
                result = key_manager.deduct_balance(key_value, img_count)
                if result.get("clamped"):
                    print(f"[BALANCE] Key {result['key_id']} 余额耗尽，扣除 ${result['deducted']:.4f}，{img_count} 张")
                else:
                    print(f"[BALANCE] Key {result['key_id']} 扣除 ${result['deducted']:.4f}（{img_count} 张），余额 ${result['balance_after']:.4f}")
        except Exception as e:
            print(f"[BALANCE] 扣减失败（不影响生成）: {e}")

    except Exception as e:
        print(f"[ERROR] Background task {task_id} failed: {e}")
        _active_tasks.discard(task_id)
        p = task_store.get(task_id)
        if p:
            user_id_val = p.get("user_id", user_id)
            charge_val = p.get("charge_points", charge_points)
            _try_refund_generation(p, user_id_val, task_id, charge_val, "生成失败自动退回")
            p["status"] = "error"
            p["error"] = str(e)
            save_task_progress(task_id, p)
            push_event(task_id, {"status": "failed", "error": str(e)})
        else:
            _try_refund_generation({}, user_id, task_id, charge_points, "生成失败自动退回")
        add_history(
            task_id=task_id,
            api_key_id=None,
            user_id=user_id,
            product_type=sanitize_input(req.product_type, 50),
            country=sanitize_input(req.country, 20),
            model=sanitize_input(req.model, 20),
            status="failed",
            error_msg=str(e)[:500],
            description_snapshot=_history_description_snapshot(req),
        )


@app.post("/api/generate/async")
@limiter.limit("20/minute")
async def generate_async(
    request: Request,
    req: GenerateRequest,
    _=Depends(verify_api_auth),
    user: dict = Depends(authenticate_customer),
):
    """异步启动图片生成，立即返回 task_id"""
    _verify_user_csrf(request, user)
    validate_image_data(str(req.image_url))
    ensure_api_key_available()
    client_ip = request.client.host if request.client else "unknown"
    task_id = init_progress(TOTAL_GENERATION_IMAGES, creator_ip=client_ip)
    user_id = int(user["id"])
    charge_points = req.charge_points if req.charge_points is not None else get_generation_cost_points()
    try:
        charge_generation(user_id, task_id, charge_points, f"生成任务 {task_id}")
    except ValueError:
        task_store.pop(task_id, None)
        raise HTTPException(status_code=402, detail="积分不足，请先充值")
    task_store[task_id]["user_id"] = user_id
    task_store[task_id]["charge_points"] = charge_points
    save_task_progress(task_id, task_store[task_id])
    _active_tasks.add(task_id)
    task = asyncio.create_task(_run_generation_background(task_id, req, user_id, charge_points))
    task.add_done_callback(lambda t: _cleanup_active_task(task_id, t))
    print(f"[START] Background task created: {task_id} (IP: {client_ip})")
    return {
        "task_id": task_id,
        "charge_points": charge_points,
        "total_images": TOTAL_GENERATION_IMAGES,
        "model_image_count": req.model_image_count,
    }


@app.get("/api/generate/status/{task_id}")
@limiter.limit("30/minute")
async def generate_status(
    request: Request,
    task_id: str,
    _=Depends(verify_api_auth),
    user: dict = Depends(authenticate_customer),
):
    """查询实时进度（仅允许任务创建者查询）"""
    p = get_task_for_request(task_id, request, user)

    elapsed = time.time() - p["start_time"]
    event = build_progress_event(p)
    return {
        "status": p["status"],
        "total": event["total"],
        "completed": event["completed"],
        "elapsed_seconds": round(elapsed, 1),
        "images": event["images"],
        "result": event.get("result"),
        "error": event.get("error"),
        "partial": event.get("partial"),
        "success_count": event.get("success_count"),
        "total_count": event.get("total_count"),
    }


@app.get("/api/generate/status/{task_id}/stream")
async def generate_status_stream(
    request: Request,
    task_id: str,
    _=Depends(verify_api_auth),
    user: dict = Depends(authenticate_customer),
):
    """SSE 实时进度流"""
    progress = get_task_for_request(task_id, request, user)
    return StreamingResponse(
        sse_stream(task_id, initial_event=build_progress_event(progress)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ========== 自定义产品类型持久化 ==========


@app.get("/api/custom-types")
async def list_custom_types(user: dict = Depends(authenticate_customer)):
    return {"types": get_custom_types(int(user["id"]))}


@app.post("/api/custom-types")
@limiter.limit("30/minute")
async def create_custom_type(request: Request, req: CreateCustomTypeRequest, user: dict = Depends(authenticate_customer)):
    _verify_user_csrf(request, user)
    label = sanitize_input(req.label, 100)
    category = sanitize_input(req.category, 50)
    tid = add_custom_type(label, category, int(user["id"]))
    return {"id": tid, "label": label, "category": category}


@app.delete("/api/custom-types/{type_id}")
@limiter.limit("30/minute")
async def remove_custom_type(request: Request, type_id: int, user: dict = Depends(authenticate_customer)):
    _verify_user_csrf(request, user)
    ok = delete_custom_type(type_id, int(user["id"]))
    if not ok:
        raise HTTPException(status_code=404, detail="类型不存在")
    return {"message": "删除成功"}


# ========== 管理后台端点 ==========

@app.post("/admin/login")
@limiter.limit("5/minute")
async def admin_login(request: Request, req: LoginRequest):
    """管理员登录 — 返回 JSON (含 csrf_token) + 设置 HttpOnly Cookie"""
    username = sanitize_input(req.username, 50)
    result = await login(username, req.password)
    from security import verify_token
    payload = verify_token(result["access_token"])
    result["csrf_token"] = payload["jti"] if payload else ""
    resp = JSONResponse(content=result)
    resp.set_cookie(
        key="access_token",
        value=result["access_token"],
        httponly=True,
        samesite="lax",
        path="/",
        max_age=TOKEN_EXPIRE_DAYS * 24 * 3600,
        secure=COOKIE_SECURE,
    )
    return resp


@app.get("/admin/me")
async def admin_me(user: dict = Depends(authenticate)):
    """获取当前登录用户信息 — 用于前端初始化检测会话"""
    return {
        "username": user.get("sub"),
        "role": user.get("role"),
        "csrf_token": user.get("jti", ""),
    }


@app.post("/admin/refresh")
async def admin_refresh(user: dict = Depends(authenticate)):
    """刷新 token（延长有效期）— 旧 token 被吊销"""
    from database import revoke_jti
    # Revoke old token's jti
    if user.get("jti"):
        exp = user.get("exp", "")
        revoke_jti(user["jti"], str(exp) if exp else "")
    new_token = refresh_token(user)
    expires_in = JWT_EXPIRE_MINUTES * 60
    resp = JSONResponse(content={
        "access_token": new_token,
        "token_type": "bearer",
        "expires_in": expires_in,
    })
    resp.set_cookie(
        key="access_token",
        value=new_token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=expires_in,
        secure=COOKIE_SECURE,
    )
    return resp


@app.post("/admin/logout")
async def admin_logout(request: Request, _csrf=Depends(verify_csrf)):
    """登出 — 清除 cookie 并吊销 token"""
    # Revoke the current token's jti
    token = request.cookies.get("access_token", "")
    if token:
        from security import verify_token
        from database import revoke_jti
        payload = verify_token(token)
        if payload and payload.get("jti"):
            exp = payload.get("exp", "")
            revoke_jti(payload["jti"], str(exp) if exp else "")
    resp = JSONResponse(content={"message": "已登出"})
    resp.set_cookie(
        key="access_token",
        value="",
        httponly=True,
        samesite="lax",
        path="/",
        max_age=0,
        secure=COOKIE_SECURE,
    )
    return resp


@app.get("/admin/dashboard")
@limiter.limit("30/minute")
async def admin_dashboard(request: Request, user: dict = Depends(authenticate)):
    """仪表盘概览"""
    stats = get_dashboard_stats()
    keys_health = key_manager.health_check()
    return {**stats, "keys_health": keys_health}


@app.get("/admin/api-keys")
async def list_api_keys(user: dict = Depends(authenticate)):
    """列出所有 API Key（脱敏显示）"""
    return {"keys": get_all_keys_masked()}


@app.post("/admin/api-keys")
@limiter.limit("10/minute")
async def create_api_key(request: Request, req: CreateApiKeyRequest, user: dict = Depends(authenticate), _csrf=Depends(verify_csrf)):
    """添加 API Key"""
    from sqlite3 import IntegrityError
    import logging as _log
    _logger = _log.getLogger("ecommerce-gen.api-keys")
    key_value = sanitize_input(req.key_value, 500)
    name = sanitize_input(req.name, 100)
    try:
        kid = add_key(key_value, name, req.daily_limit)
    except IntegrityError as e:
        _logger.warning(f"Duplicate key insert rejected: {e}")
        raise HTTPException(status_code=409, detail="该 Key 已存在，不能重复添加")
    except Exception as e:
        _logger.error(f"add_key failed: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存失败: {type(e).__name__}: {e}")
    return {"id": kid, "message": "Key 添加成功"}


@app.put("/admin/api-keys/{key_id}")
@limiter.limit("10/minute")
async def modify_api_key(request: Request, key_id: int, req: dict, user: dict = Depends(authenticate), _csrf=Depends(verify_csrf)):
    """更新 API Key"""
    kwargs = {}
    if "name" in req:
        kwargs["name"] = sanitize_input(req["name"], 100)
    if "is_active" in req:
        kwargs["is_active"] = int(req["is_active"])
    if "daily_limit" in req:
        kwargs["daily_limit"] = int(req["daily_limit"])
    if "balance_usd" in req:
        try:
            balance = float(req["balance_usd"])
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="balance_usd must be a number")
        if balance < 0:
            raise HTTPException(status_code=400, detail="balance_usd must be >= 0")
        kwargs["balance_usd"] = balance
    ok = db_update_key(key_id, **kwargs)
    if not ok:
        raise HTTPException(status_code=404, detail="Key 不存在")
    return {"message": "更新成功"}


@app.delete("/admin/api-keys/{key_id}")
@limiter.limit("10/minute")
async def remove_api_key(request: Request, key_id: int, user: dict = Depends(authenticate), _csrf=Depends(verify_csrf)):
    """删除 API Key"""
    ok = db_delete_key(key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key 不存在")
    return {"message": "删除成功"}


@app.get("/admin/history")
async def admin_history(
    page: int = 1,
    per_page: int = 20,
    status: str = "",
    search: str = "",
    user: dict = Depends(authenticate),
):
    """生成历史记录"""
    return get_history(page, per_page, sanitize_input(status, 20), sanitize_input(search, 100))


@app.get("/admin/history/{history_id}")
async def admin_history_detail(history_id: int, user: dict = Depends(authenticate)):
    """获取单条历史详情"""
    from database import get_history_detail
    detail = get_history_detail(history_id)
    if not detail:
        raise HTTPException(status_code=404, detail="记录不存在")
    # 解析 JSON 字段供前端直接使用
    import json
    for field in ("llm_request", "llm_response", "tasks_detail"):
        if detail.get(field):
            try:
                detail[field] = json.loads(detail[field])
            except (json.JSONDecodeError, TypeError):
                pass
    return detail


@app.get("/admin/credit-packages")
async def admin_credit_packages(user: dict = Depends(authenticate)):
    return {
        "packages": list_credit_packages(include_inactive=True),
        "generation_cost_points": get_generation_cost_points(),
    }


@app.post("/admin/credit-packages")
@limiter.limit("20/minute")
async def admin_create_credit_package(
    request: Request,
    req: CreditPackageRequest,
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    package_id = upsert_credit_package(
        req.name,
        req.price_fen,
        req.points,
        req.bonus_points,
        req.status,
        req.sort_order,
    )
    return {"id": package_id}


@app.put("/admin/credit-packages/{package_id}")
@limiter.limit("20/minute")
async def admin_update_credit_package(
    request: Request,
    package_id: int,
    req: CreditPackageRequest,
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    try:
        upsert_credit_package(
            req.name,
            req.price_fen,
            req.points,
            req.bonus_points,
            req.status,
            req.sort_order,
            package_id=package_id,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="套餐不存在")
    return {"message": "updated"}


@app.delete("/admin/credit-packages/{package_id}")
@limiter.limit("20/minute")
async def admin_delete_credit_package(
    request: Request,
    package_id: int,
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    deleted = delete_credit_package(package_id)
    if not deleted:
        raise HTTPException(
            status_code=409,
            detail="该套餐已有关联订单，无法删除。可改为停用。",
        )
    return {"message": "deleted"}


@app.put("/admin/generation-cost")
@limiter.limit("20/minute")
async def admin_update_generation_cost(
    request: Request,
    req: dict,
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    try:
        points = int(req.get("points", 10))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="points must be an integer")
    if points < 1:
        raise HTTPException(status_code=400, detail="扣费积分必须大于 0")
    set_config("generation_cost_points", str(points))
    return {"generation_cost_points": points}


@app.get("/admin/orders")
async def admin_orders(user: dict = Depends(authenticate)):
    return {"orders": list_all_orders()}


@app.post("/admin/orders/{order_no}/mark-paid")
@limiter.limit("20/minute")
async def admin_mark_order_paid(
    request: Request,
    order_no: str,
    req: dict = {},
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    try:
        order = mark_order_paid(
            sanitize_input(order_no, 80),
            provider_trade_no=f"manual-{uuid.uuid4().hex[:10]}",
            reviewer_note=str(req.get("reviewer_note", "")),
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="订单不存在或状态不可入账")
    return {"order": order}


@app.post("/admin/orders/{order_no}/reject")
@limiter.limit("20/minute")
async def admin_reject_order(
    request: Request,
    order_no: str,
    req: dict,
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    reason = str(req.get("reject_reason", "")).strip()
    if not reason:
        raise HTTPException(status_code=422, detail="驳回原因不能为空")
    try:
        order = reject_order(sanitize_input(order_no, 80), sanitize_input(reason, 500))
    except ValueError as e:
        if str(e) == "order_not_found":
            raise HTTPException(status_code=404, detail="订单不存在")
        if str(e) == "order_not_rejectable":
            raise HTTPException(status_code=400, detail="订单当前状态不可驳回")
        raise
    return {"order": order}


@app.get("/admin/health")
async def admin_health(user: dict = Depends(authenticate)):
    """系统健康状态"""
    from datetime import datetime
    return {
        "status": "healthy",
        "server_time": datetime.now().isoformat(),
        "task_store_size": len(task_store),
        "keys_health": key_manager.health_check(),
    }


# ========== 账号管理端点 ==========


@app.get("/admin/users")
@limiter.limit("30/minute")
async def admin_list_users(request: Request, user: dict = Depends(authenticate)):
    """获取所有用户列表"""
    return {"users": list_all_users()}


@app.post("/admin/users")
@limiter.limit("20/minute")
async def admin_create_user_endpoint(
    request: Request,
    req: AdminCreateUserRequest,
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    """管理员创建新用户（无需密码强校验）"""
    username = sanitize_input(req.username, 50)
    phone = sanitize_input(req.phone, 30)
    email = sanitize_input(req.email, 120)
    note = sanitize_input(req.note, 500)
    if not req.password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    try:
        user_id = admin_create_user(username, hash_password(req.password), phone=phone, email=email, note=note, is_unlimited=req.is_unlimited)
    except ValueError:
        raise HTTPException(status_code=409, detail="用户名已存在")
    return {"id": user_id, "username": username}


@app.put("/admin/users/{user_id}/status")
@limiter.limit("30/minute")
async def admin_update_user_status(
    request: Request,
    user_id: int,
    req: AdminUserStatusRequest,
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    """冻结/解冻用户"""
    # 防止管理员冻结/解冻自己
    # 注意：管理员存在 users 表，get_customer_by_id 查 customers 表，
    # 对管理员账号返回 None，此检查自然放行；对客户账号则正常拦截自冻操作。
    from database import get_customer_by_id
    admin_username = user.get("sub", "")
    target = get_customer_by_id(user_id)
    if target and target["username"] == admin_username:
        raise HTTPException(status_code=400, detail="不能对自己的账号执行此操作")
    ok = update_user_status(user_id, req.status)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"message": "已更新", "status": req.status}


@app.put("/admin/users/{user_id}/note")
@limiter.limit("30/minute")
async def admin_update_user_note(
    request: Request,
    user_id: int,
    req: AdminUserNoteRequest,
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    """更新用户备注"""
    note = sanitize_input(req.note, 500)
    ok = update_user_note(user_id, note)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"message": "备注已更新"}


@app.delete("/admin/users/{user_id}")
@limiter.limit("20/minute")
async def admin_delete_user_endpoint(
    request: Request,
    user_id: int,
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    """删除用户"""
    # 防止管理员删除自己
    from database import get_customer_by_id
    admin_username = user.get("sub", "")
    target = get_customer_by_id(user_id)
    if target and target["username"] == admin_username:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    ok = delete_user(user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"message": "用户已删除"}


@app.put("/admin/change-password")
@limiter.limit("5/minute")
async def admin_change_password(
    request: Request,
    req: AdminChangePasswordRequest,
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    """管理员修改自己的密码"""
    from database import revoke_jti
    username = user.get("sub", "")
    admin = get_user(username)
    if not admin:
        raise HTTPException(status_code=404, detail="管理员账号不存在")
    if not req.new_password.strip():
        raise HTTPException(status_code=400, detail="密码不能为空")
    update_admin_password(username, hash_password(req.new_password))
    # Revoke current token to force re-login
    if user.get("jti"):
        exp = user.get("exp", "")
        revoke_jti(user["jti"], str(exp) if exp else "")
    resp = JSONResponse(content={"message": "密码修改成功，请重新登录"})
    resp.set_cookie(key="user_access_token", value="", httponly=True, samesite="lax", path="/", max_age=0, secure=COOKIE_SECURE)
    return resp


# ========== LLM 配置管理端点 ==========


@app.get("/admin/llm-config")
async def get_llm_config(user: dict = Depends(authenticate)):
    """获取当前 LLM 配置（Key 脱敏）"""
    api_key = get_config("llm_api_key") or ""
    model = get_config("llm_model") or "qwen3-vl-flash"
    return {
        "api_key": mask_api_key(api_key) if api_key else "",
        "has_key": bool(api_key),
        "key_length": len(api_key) if api_key else 0,
        "model": model,
    }


@app.put("/admin/llm-config")
@limiter.limit("10/minute")
async def update_llm_config(request: Request, body: dict, user: dict = Depends(authenticate), _csrf=Depends(verify_csrf)):
    """更新 LLM 配置"""
    if "api_key" in body:
        val = body["api_key"].strip()
        if val:
            set_config("llm_api_key", val)
        else:
            set_config("llm_api_key", "")
    if "model" in body:
        val = body["model"].strip()
        if val:
            set_config("llm_model", val)
    return {"message": "LLM 配置已更新"}


@app.post("/admin/llm-config/test")
@limiter.limit("5/minute")
async def test_llm_config(request: Request, body: dict, user: dict = Depends(authenticate), _csrf=Depends(verify_csrf)):
    """测试 LLM 连接"""
    raw_key = body.get("api_key", "").strip()
    # 如果前端发的 key 是脱敏后的（含 ****），用数据库里的真实 key
    api_key = raw_key if "****" not in raw_key else (get_config("llm_api_key") or "")
    model = body.get("model", "").strip() or get_config("llm_model") or "qwen3-vl-flash"

    if not api_key:
        return {"success": False, "error": "API Key 未配置"}

    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "user", "content": "请回复：连接测试成功，模型已就绪"}
                    ],
                },
            )
        if resp.status_code == 200:
            reply = resp.json()["choices"][0]["message"]["content"]
            return {"success": True, "reply": reply}
        else:
            return {"success": False, "error": f"API 返回 {resp.status_code}: {resp.text[:200]}"}
    except httpx.ConnectError:
        return {"success": False, "error": "无法连接到百炼 API"}
    except Exception as e:
        return {"success": False, "error": str(e)[:200]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
