"""
FastAPI 图片生成后端
接管原 Next.js /api/generate 的完整流程：
上传图片 → 品类匹配 → prompt 构建 → apimart 批量生成 → 轮询 → 返回结果
"""

import asyncio
import base64
import json
import re
import secrets
import time
import os
import sys
import uuid
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import httpx
import traceback
from dotenv import load_dotenv

# 必须在导入依赖 JWT_SECRET 的模块前加载 .env
load_dotenv()

from prompts_v2 import (
    match_category,
    select_model,
    get_model_profile,
    generate_all_tasks,
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
    get_all_custom_types, add_custom_type, delete_custom_type,
    charge_generation, create_customer, create_order, get_active_keys, get_generation_cost_points,
    get_wallet, list_all_orders, list_credit_packages, list_user_history,
    list_user_ledger, list_user_orders, mark_order_paid,
    upsert_credit_package, get_user, create_user, ensure_refund_once,
    mask_api_key, update_admin_password,
)
from llm_provider import analyze as llm_analyze, build_llm_messages

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
    # 自动导入 API Key
    try:
        from database import get_key_by_value, add_key
        api_key = os.getenv("APIMART_API_KEY", "")
        if api_key and not get_key_by_value(api_key):
            add_key(api_key, name="默认 Key", daily_limit=200)
            print(f"[INIT] API Key 已导入")
    except Exception as e:
        print(f"[INIT] API Key 导入失败: {e}")
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

# ========== Apimart 配置 ==========
APIMART_BASE = "https://api.apimart.ai/v1"
MAX_CONCURRENT = 3  # 每次最多 3 个并发请求


# ========== 请求/响应模型 ==========
class GenerateRequest(BaseModel):
    image_url: str
    product_type: str = Field(default="", max_length=200)
    country: str = Field(
        default="japan",
        pattern=r"^(japan|korea|usa|thailand|vietnam|malaysia|philippines|indonesia|china)$",
    )
    model: str = "general"
    generate_type: str = Field(default="all", pattern=r"^(all|comparison|detail|test)$")
    style_index: int = Field(default=0, ge=0, le=10)
    prompt_size: str = Field(default="auto", pattern=r"^(auto|1:1|4:3|3:4|16:9|9:16)$")
    prompt_resolution: str = Field(default="1k", pattern=r"^(1k|2k|4k)$")
    model_image_count: int = Field(default=4, ge=0, le=9)


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


# ========== Apimart API 工具函数 ==========
async def _apimart_request(url: str, method: str = "POST", json_body: dict = None, retries: int = 3):
    """带重试和多 Key 支持的 apimart API 请求"""
    key_row = key_manager.get_active_key()
    if not key_row:
        raise HTTPException(status_code=409, detail="所有 API Key 均已失效，请到后台检查或添加新 Key")

    api_key = key_row["key_value"]

    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }
                if method == "POST":
                    resp = await client.post(url, headers=headers, json=json_body)
                else:
                    resp = await client.get(url, headers=headers)

                if resp.status_code == 200:
                    key_manager.mark_success(api_key)
                    return resp.json()

                # Only authentication/permission failures prove the key itself is bad.
                if resp.status_code in (401, 403):
                    key_manager.mark_failure(api_key)
                    new_key = key_manager.get_active_key()
                    if new_key:
                        api_key = new_key["key_value"]
                        print(f"  Key 失效，切换到: {api_key[:15]}...")
                        continue
                    raise HTTPException(status_code=502, detail="所有 API Key 鉴权均失败，请到后台检查 Key 状态")

                # Quota/payment failures should be surfaced, not counted as auth failure.
                if resp.status_code == 402:
                    raise HTTPException(status_code=402, detail="Apimart API Key 额度不足或账号未开通 (402)")

                error_body = resp.json() if resp.text else {}
                raise HTTPException(
                    status_code=502,
                    detail=error_body.get("error", {}).get("message", f"Apimart {resp.status_code}"),
                )
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as e:
            if attempt < retries - 1:
                delay = 2 * (attempt + 1)
                print(f"  [重试 {attempt+1}/{retries-1}] 网络错误，{delay}s 后重试...")
                await asyncio.sleep(delay)
            else:
                raise HTTPException(status_code=502, detail="上游 API 网络连接失败，请稍后重试")


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

    result = await _apimart_request(f"{APIMART_BASE}/images/generations", "POST", body)
    task_id = result["data"][0].get("task_id")
    if not task_id:
        raise HTTPException(status_code=502, detail="未返回 task_id")

    # 等待（文档建议 10-20s）
    await asyncio.sleep(15)

    # 轮询
    for round_num in range(30):
        qr = await _query_single_task(task_id)
        if isinstance(qr, str) and qr != "failed":
            return qr
        if qr == "failed":
            raise HTTPException(status_code=502, detail="图片生成任务失败")
        if isinstance(qr, dict):
            print(f"  [轮询 #{round_num+1}] status={qr['status']}, progress={qr.get('progress', 0)}")
        await asyncio.sleep(4)

    raise HTTPException(status_code=502, detail="任务轮询超时")


async def apimart_batch_generate(
    tasks: list[dict],
    fallback_url: str,
    on_progress: Optional[callable] = None,
) -> list[str]:
    """
    批量生成：分批提交 → 统一等待 → 批量轮询
    tasks: [{prompt, reference_url, size, resolution}, ...]
    on_progress: 可选回调 (index, url) — 每完成一张图时调用
    """
    total = len(tasks)
    print(f"\n[BATCH] apimart batch generate: submitting {total} tasks (concurrency {MAX_CONCURRENT})...")

    # Step 1: 分批提交
    submissions = []  # [(index, task_id)]
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

    task_ids = [tid for _, tid in submissions]
    task_map = {tid: idx for idx, tid in submissions}
    print(f"\n[PROGRESS] Submitted: {len(task_ids)}/{total}")

    if not task_ids:
        return [fallback_url] * total

    # Step 2: 等待 15s（文档建议 10-20s）
    await asyncio.sleep(15)

    # Step 3: 批量轮询 — 带早失败和超时保护
    results = [None] * total
    no_progress_count = 0
    MAX_NO_PROGRESS = 5  # 连续 5 轮无进展则提前终止

    for round_num in range(30):
        pending = [tid for tid in task_ids if results[task_map[tid]] is None]
        if not pending:
            break

        completed_this_round = 0
        fatal_error = None

        try:
            query_results = await asyncio.gather(
                *[_query_single_task(tid) for tid in pending],
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
                    results[idx] = None  # 标记为失败，最终用 fallback
                    completed_this_round += 1
                    if on_progress:
                        on_progress(idx, None)
                elif isinstance(qr, HTTPException):
                    fatal_error = qr
                    break
                elif isinstance(qr, dict):
                    pass  # pending/processing，继续等
                # elif qr is None: 网络错误，继续等

        except Exception as e:
            print(f"  [轮询 #{round_num+1}] 批量查询出错: {e}")

        if fatal_error:
            print(f"  [FATAL] 致命错误，终止轮询: {fatal_error.detail}")
            for i, r in enumerate(results):
                if r is None and on_progress:
                    on_progress(i, fallback_url)
            return [r if r else fallback_url for r in results]

        # 本轮无进展计数
        if completed_this_round == 0:
            no_progress_count += 1
            if no_progress_count >= MAX_NO_PROGRESS:
                print(f"  [TIMEOUT] 连续 {MAX_NO_PROGRESS} 轮无进展，提前终止")
                break
        else:
            no_progress_count = 0

        remaining = sum(1 for r in results if r is None)
        print(f"  [轮询 #{round_num+1}] +{completed_this_round} done, remaining {remaining}/{total}")

        if remaining == 0:
            break
        await asyncio.sleep(4)

    # 未完成的用 fallback
    final_results = [r if r else fallback_url for r in results]
    for i, r in enumerate(results):
        if r is None and on_progress:
            on_progress(i, fallback_url)
    return final_results


async def _submit_task(task: dict, index: int, total: int) -> tuple[int, str]:
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

        result = await _apimart_request(f"{APIMART_BASE}/images/generations", "POST", body)
        tid = result["data"][0]["task_id"]
        print(f"  [{index+1}/{total}] 已提交: {tid}")
        return (index, tid)
    except Exception as e:
        print(f"  [{index+1}/{total}] 提交失败: {e}")
        raise


async def _query_single_task(task_id: str):
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
        task = await _apimart_request(f"{APIMART_BASE}/tasks/{task_id}", "GET")
        data = task.get("data", {})
        status = data.get("status")

        if status == "completed":
            try:
                return data["result"]["images"][0]["url"][0]
            except (KeyError, IndexError):
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
    except HTTPException:
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
    order_no = f"MOCK{int(time.time())}{uuid.uuid4().hex[:8].upper()}"
    try:
        order = create_order(int(user["id"]), req.package_id, order_no)
    except ValueError:
        raise HTTPException(status_code=404, detail="套餐不存在或已下架")
    return {"order": order, "payment": {"provider": "mock", "status": "pending"}}


@app.get("/user/orders")
async def user_orders(user: dict = Depends(authenticate_customer)):
    return {"orders": list_user_orders(int(user["id"]))}


@app.get("/user/ledger")
async def user_ledger(user: dict = Depends(authenticate_customer)):
    return {"items": list_user_ledger(int(user["id"]))}


@app.get("/user/history")
async def user_history(user: dict = Depends(authenticate_customer)):
    return {"items": list_user_history(int(user["id"]))}


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
    charge_points = get_generation_cost_points()
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

        # LLM 智能分析（失败时静默降级）
        llm_config = None
        llm_request_data = ""
        llm_response_data = ""
        if get_config("llm_api_key"):
            try:
                llm_messages = build_llm_messages(
                    image_url=hosted_image_url if hosted_image_url else None,
                    product_type=req.product_type,
                    country_name=country_config["name"],
                    platform=country_config["platform"],
                    model_name=model_profile["name"],
                    model_tagline=model_profile["tagline"],
                    category_name=category["name"],
                    shot_type=category.get("shot_type", "product"),
                )
                llm_request_data = json.dumps(llm_messages, ensure_ascii=False)
                llm_config = await llm_analyze(
                    image_url=hosted_image_url if hosted_image_url else None,
                    product_type=req.product_type,
                    country_name=country_config["name"],
                    platform=country_config["platform"],
                    model_name=model_profile["name"],
                    model_tagline=model_profile["tagline"],
                    category_name=category["name"],
                    shot_type=category.get("shot_type", "product"),
                )
                if llm_config:
                    llm_response_data = json.dumps(llm_config, ensure_ascii=False)
                    print(f"  [LLM] Analysis successful")
            except Exception as e:
                print(f"  [WARN] LLM analysis failed (downgrading to template): {e}")

        # 2. 单图生成模式
        if req.generate_type == "comparison":
            prompt = build_comparison_prompt(req.product_type, category)
            print("[COMPARISON] Generating comparison image...")
            url = await apimart_generate(prompt, hosted_image_url, req.prompt_size, req.prompt_resolution)
            add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                        country=sanitize_input(req.country, 20), model=model_code, status="completed",
                        elapsed_seconds=round(time.time() - start, 1), charge_points=charge_points,
                        description_snapshot=sanitize_input(req.product_type, 200),
                        preview_images_json=_preview_images([url]))
            return {"success": True, "data": {"comparisonImage": url}}

        if req.generate_type == "detail":
            prompt = build_detail_prompt(req.product_type, category)
            print("[DETAIL] Generating detail image...")
            url = await apimart_generate(prompt, hosted_image_url, req.prompt_size, req.prompt_resolution)
            add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                        country=sanitize_input(req.country, 20), model=model_code, status="completed",
                        elapsed_seconds=round(time.time() - start, 1), charge_points=charge_points,
                        description_snapshot=sanitize_input(req.product_type, 200),
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
                llm_config=llm_config,
                model_image_count=req.model_image_count,
            )
            url = await apimart_generate(
                gen_result["tasks"][idx]["prompt"],
                gen_result["tasks"][idx]["reference_url"],
                req.prompt_size, req.prompt_resolution,
            )
            model_profile = gen_result["model_profile"]
            model_styles = MODEL_STYLE_NAMES
            tasks_detail = _build_tasks_detail(gen_result["tasks"], [url])
            add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                        country=sanitize_input(req.country, 20), model=model_code, status="completed",
                        elapsed_seconds=round(time.time() - start, 1),
                        llm_request=llm_request_data, llm_response=llm_response_data,
                        tasks_detail=tasks_detail, charge_points=charge_points,
                        description_snapshot=sanitize_input(gen_result.get("description", req.product_type), 500),
                        preview_images_json=_preview_images([url]))
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
                    "tags": gen_result.get("tags", []),
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
            llm_config=llm_config,
            model_image_count=req.model_image_count,
        )

        urls = await apimart_batch_generate(gen_result["tasks"], hosted_image_url)

        split = _split_generation_urls(urls, req.model_image_count)
        main_images = split["main_images"]
        model_images = split["model_images"]
        product_images = split["product_images"]
        detail_url = split["detail_image"]
        comparison_url = split["comparison_image"]

        elapsed = time.time() - start
        success_count = sum(1 for u in urls if u and not u.startswith("data:"))
        tasks_detail = _build_tasks_detail(gen_result["tasks"], urls)
        add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                    country=sanitize_input(req.country, 20), model=model_code, total_images=TOTAL_GENERATION_IMAGES,
                    success_count=success_count, status="completed", elapsed_seconds=round(elapsed, 1),
                    llm_request=llm_request_data, llm_response=llm_response_data,
                    tasks_detail=tasks_detail, charge_points=charge_points,
                    description_snapshot=sanitize_input(gen_result.get("description", req.product_type), 500),
                    preview_images_json=_preview_images(model_images))
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
            "tags": gen_result.get("tags", country_config["hashtags"]),
        },
    }
    except HTTPException as e:
        print(f"[ERROR] Sync task {task_id} failed: {e.detail}")
        if charge_state["charged"]:
            _try_refund_generation(charge_state, user_id, task_id, charge_points, "生成失败自动退回")
        add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                    country=sanitize_input(req.country, 20), model="", status="failed", error_msg=str(e.detail)[:500],
                    description_snapshot=sanitize_input(req.product_type, 500))
        raise
    except Exception as e:
        print(f"[ERROR] Sync task {task_id} failed: {e}")
        if charge_state["charged"]:
            _try_refund_generation(charge_state, user_id, task_id, charge_points, "生成失败自动退回")
        add_history(task_id=task_id, api_key_id=None, user_id=user_id, product_type=sanitize_input(req.product_type, 50),
                    country=sanitize_input(req.country, 20), model="", status="failed", error_msg=str(e)[:500],
                    description_snapshot=sanitize_input(req.product_type, 500))
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

        # LLM 智能分析（失败时静默降级）
        llm_config = None
        llm_request_data = ""
        llm_response_data = ""
        if get_config("llm_api_key"):
            try:
                llm_messages = build_llm_messages(
                    image_url=hosted_image_url if hosted_image_url else None,
                    product_type=req.product_type,
                    country_name=country_config["name"],
                    platform=country_config["platform"],
                    model_name=model_profile["name"],
                    model_tagline=model_profile["tagline"],
                    category_name=category["name"],
                    shot_type=category.get("shot_type", "product"),
                )
                llm_request_data = json.dumps(llm_messages, ensure_ascii=False)
                llm_config = await llm_analyze(
                    image_url=hosted_image_url if hosted_image_url else None,
                    product_type=req.product_type,
                    country_name=country_config["name"],
                    platform=country_config["platform"],
                    model_name=model_profile["name"],
                    model_tagline=model_profile["tagline"],
                    category_name=category["name"],
                    shot_type=category.get("shot_type", "product"),
                )
                if llm_config:
                    llm_response_data = json.dumps(llm_config, ensure_ascii=False)
                    print(f"  [LLM] Analysis successful: {len(llm_config.get('scene_config', {}).get('scenes', []))} scenes, {len(llm_config.get('metadata', {}).get('titles', []))} titles")
            except Exception as e:
                print(f"  [WARN] LLM analysis failed (downgrading to template): {e}")

        # 生成任务
        gen_result = generate_all_tasks(
            req.product_type, hosted_image_url,
            req.country, req.model,
            req.prompt_size, req.prompt_resolution,
            category=category,
            country_config=country_config,
            model_code=model_code,
            model_profile=model_profile,
            llm_config=llm_config,
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

        progress["status"] = "generating"
        save_task_progress(task_id, progress)
        push_event(task_id, {"status": "generating", "total": progress["total"], "completed": 0})

        # 批量生成
        urls = await apimart_batch_generate(
            gen_result["tasks"], hosted_image_url, on_progress
        )

        # 构建结果
        split = _split_generation_urls(urls, req.model_image_count)
        main_images = split["main_images"]
        model_images = split["model_images"]
        product_images = split["product_images"]
        detail_url = split["detail_image"]
        comparison_url = split["comparison_image"]

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
                "tags": gen_result.get("tags", country_config["hashtags"]),
            },
        }
        progress["status"] = "completed"
        save_task_progress(task_id, progress)
        push_event(task_id, {"status": "completed", "result": progress["result"]})
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
            llm_request=llm_request_data,
            llm_response=llm_response_data,
            tasks_detail=tasks_detail_json,
            charge_points=charge_points,
            description_snapshot=sanitize_input(gen_result.get("description", req.product_type), 500),
            preview_images_json=_preview_images(model_images),
        )

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
            description_snapshot=sanitize_input(req.product_type, 500),
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
    charge_points = get_generation_cost_points()
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
    return {
        "status": p["status"],
        "total": p["total"],
        "completed": p["completed"],
        "elapsed_seconds": round(elapsed, 1),
        "images": [
            {"index": img["index"], "status": img["status"], "url": img["url"], "name": img["name"]}
            for img in p["images"]
        ],
        "result": p.get("result"),
        "error": p.get("error"),
    }


@app.get("/api/generate/status/{task_id}/stream")
async def generate_status_stream(
    request: Request,
    task_id: str,
    _=Depends(verify_api_auth),
    user: dict = Depends(authenticate_customer),
):
    """SSE 实时进度流"""
    get_task_for_request(task_id, request, user)
    return StreamingResponse(
        sse_stream(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ========== 自定义产品类型持久化 ==========


@app.get("/api/custom-types")
async def list_custom_types():
    return {"types": get_all_custom_types()}


@app.post("/api/custom-types")
@limiter.limit("30/minute")
async def create_custom_type(request: Request, req: CreateCustomTypeRequest):
    label = sanitize_input(req.label, 100)
    category = sanitize_input(req.category, 50)
    tid = add_custom_type(label, category)
    return {"id": tid, "label": label, "category": category}


@app.delete("/api/custom-types/{type_id}")
@limiter.limit("30/minute")
async def remove_custom_type(request: Request, type_id: int):
    ok = delete_custom_type(type_id)
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
    key_value = sanitize_input(req.key_value, 500)
    name = sanitize_input(req.name, 100)
    kid = add_key(key_value, name, req.daily_limit)
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
    user: dict = Depends(authenticate),
    _csrf=Depends(verify_csrf),
):
    try:
        order = mark_order_paid(sanitize_input(order_no, 80), provider_trade_no=f"mock-{uuid.uuid4().hex[:10]}")
    except ValueError:
        raise HTTPException(status_code=404, detail="订单不存在或状态不可入账")
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
