"""
FastAPI 图片生成后端
接管原 Next.js /api/generate 的完整流程：
上传图片 → 品类匹配 → prompt 构建 → apimart 批量生成 → 轮询 → 返回结果
"""

import asyncio
import json
import re
import time
import os
import uuid
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
    COUNTRY_CONFIG,
)
from key_manager import key_manager
from security import authenticate, login, sanitize_input, refresh_token, TOKEN_EXPIRE_DAYS, JWT_EXPIRE_MINUTES
from middleware import init_rate_limiting, limiter
from database import (
    get_all_keys, get_all_keys_masked, add_key as db_add_key,
    update_key as db_update_key,
    delete_key as db_delete_key, get_history, get_dashboard_stats,
    add_history, add_key, get_key_by_value,
    save_task_progress, load_pending_tasks, delete_old_tasks, init_db,
    get_config, set_config, get_all_configs,
    get_all_custom_types, add_custom_type, delete_custom_type,
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


async def verify_api_auth(request: Request):
    """验证 API 内部认证令牌（保护生成端点不被外部直接调用）"""
    if not API_AUTH_TOKEN:
        return True
    auth_header = request.headers.get("X-API-Auth", "")
    if auth_header != API_AUTH_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常：过滤敏感路径信息"""
    if isinstance(exc, HTTPException):
        raise exc
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
    # 自动 seed 管理员
    try:
        from database import get_user, create_user
        from security import hash_password
        admin_pw = os.getenv("ADMIN_PASSWORD", "admin123")
        if not get_user("admin"):
            create_user("admin", hash_password(admin_pw))
            print(f"[INIT] 管理员已创建 (密码: {admin_pw})")
        else:
            print("[INIT] 管理员已存在")
    except Exception as e:
        print(f"[INIT] 管理员创建失败: {e}")
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
        print(f"♻️ 恢复 {len(pending)} 个未完成任务")
        task_store.update(pending)


CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:5000").split(",")
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


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=100)


# ========== 进度存储 ==========
task_store: dict[str, dict] = {}

IMAGE_NAMES = [
    "模特图1", "模特图2", "模特图3", "模特图4", "模特图5",
    "模特图6", "模特图7", "模特图8", "模特图9", "模特图10", "模特图11",
    "白底展示图", "竞品对比图", "细节放大图",
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


# ========== Apimart API 工具函数 ==========
async def _apimart_request(url: str, method: str = "POST", json_body: dict = None, retries: int = 3):
    """带重试和多 Key 支持的 apimart API 请求"""
    key_row = key_manager.get_active_key()
    if not key_row:
        raise HTTPException(status_code=503, detail="没有可用的 API Key")

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

                # 认证错误 → 标记 Key 失败，换 Key 重试
                if resp.status_code in (401, 402, 403):
                    key_manager.mark_failure(api_key)
                    new_key = key_manager.get_active_key()
                    if new_key:
                        api_key = new_key["key_value"]
                        print(f"  Key 失效，切换到: {api_key[:15]}...")
                        continue
                    raise HTTPException(status_code=502, detail="所有 API Key 均已失效")

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
                key_manager.mark_failure(api_key)
                raise HTTPException(status_code=502, detail=f"Apimart 网络不可达: {str(e)}")


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

    # 等待
    await asyncio.sleep(12)

    # 轮询
    for _ in range(30):
        try:
            task = await _apimart_request(f"{APIMART_BASE}/tasks/{task_id}", "GET")
            status = task["data"].get("status")
            if status == "completed":
                url = task["data"]["result"]["images"][0]["url"][0]
                return url
            if status == "failed":
                msg = task["data"].get("error", {}).get("message", "未知错误")
                raise HTTPException(status_code=502, detail=f"任务失败: {msg}")
        except HTTPException:
            raise
        except Exception as e:
            print(f"  轮询出错: {e}")
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
    print(f"\n🎨 apimart 批量生成: 提交 {total} 个任务 (并发 {MAX_CONCURRENT})...")

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
    print(f"\n📊 已提交: {len(task_ids)}/{total}，等待处理...")

    if not task_ids:
        return [fallback_url] * total

    # Step 2: 等待 12s
    await asyncio.sleep(12)

    # Step 3: 批量轮询
    results = [None] * total
    for round_num in range(30):
        pending = [tid for tid in task_ids if results[task_map[tid]] is None]
        if not pending:
            break

        try:
            # 逐个查询（批量接口可能不稳定，逐个更可靠）
            query_results = await asyncio.gather(
                *[_query_single_task(tid) for tid in pending],
                return_exceptions=True,
            )

            completed = 0
            for tid, qr in zip(pending, query_results):
                idx = task_map.get(tid)
                if idx is None:
                    continue
                if isinstance(qr, str):  # 成功返回 URL
                    results[idx] = qr
                    completed += 1
                    if on_progress:
                        on_progress(idx, qr)
                elif qr == "failed":
                    results[idx] = None
                    if on_progress:
                        on_progress(idx, None)

            remaining = len(pending) - completed
            if remaining > 0:
                print(f"  [轮询 #{round_num+1}] completed={completed}, 剩余 {remaining}/{total}")
        except Exception as e:
            print(f"  [轮询 #{round_num+1}] 出错: {e}")

        if results.count(None) == 0:
            break
        await asyncio.sleep(4)

    final_results = [url if url else fallback_url for url in results]
    for idx, url in enumerate(results):
        if url is None and on_progress:
            on_progress(idx, fallback_url)
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


async def _query_single_task(task_id: str) -> str:
    """查询单个任务，返回 URL 或 'failed'"""
    try:
        task = await _apimart_request(f"{APIMART_BASE}/tasks/{task_id}", "GET")
        status = task["data"].get("status")
        if status == "completed":
            return task["data"]["result"]["images"][0]["url"][0]
        if status == "failed":
            return "failed"
        return None  # still processing
    except Exception:
        return None


def _build_tasks_detail(tasks: list[dict], urls: list[str] | None = None) -> str:
    """从任务列表和结果 URL 构建 tasks_detail JSON"""
    detail = []
    for i, task in enumerate(tasks):
        entry = {
            "index": i,
            "prompt": task.get("prompt", ""),
            "reference_url": task.get("reference_url", ""),
        }
        if urls and i < len(urls):
            entry["result_url"] = urls[i]
        detail.append(entry)
    return json.dumps(detail, ensure_ascii=False)


# ========== API 端点 ==========

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/generate")
@limiter.limit("10/minute")
async def generate_images(request: Request, req: GenerateRequest, _=Depends(verify_api_auth)):
    start = time.time()
    task_id = str(uuid.uuid4())

    try:
        validate_image_data(str(req.image_url))
        # 1. 智能品类匹配
        category = match_category(req.product_type)
        model_code = select_model(req.model, category)
        model_profile = get_model_profile(model_code)
        country_config = COUNTRY_CONFIG.get(req.country, COUNTRY_CONFIG["usa"])

        print(f"🚀 开始处理: {req.product_type} → {category['name']}")
        print(f"   📦 品类: {category['parent']} | 🎯 模型: {model_profile['name']} ({model_profile['tagline']})")
        print(f"   🌍 市场: {country_config['name']} ({country_config['platform']}) | 📸 拍摄方式: {category['shot_type']}")

        # LLM 智能分析（失败时静默降级）
        llm_config = None
        llm_request_data = ""
        llm_response_data = ""
        if get_config("llm_api_key"):
            try:
                llm_messages = build_llm_messages(
                    image_url=str(req.image_url) if req.image_url else None,
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
                    image_url=str(req.image_url) if req.image_url else None,
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
                    print(f"  🤖 LLM 分析成功")
            except Exception as e:
                print(f"  ⚠️ LLM 分析失败（降级至模板）: {e}")

        # 2. 单图生成模式
        if req.generate_type == "comparison":
            prompt = build_comparison_prompt(req.product_type, category)
            print("🔄 生成对比图...")
            url = await apimart_generate(prompt, req.image_url, req.prompt_size, req.prompt_resolution)
            add_history(task_id=task_id, api_key_id=None, product_type=sanitize_input(req.product_type, 50),
                        country=sanitize_input(req.country, 20), model=model_code, status="completed", elapsed_seconds=round(time.time() - start, 1))
            return {"success": True, "data": {"comparisonImage": url}}

        if req.generate_type == "detail":
            prompt = build_detail_prompt(req.product_type, category)
            print("🔍 生成细节图...")
            url = await apimart_generate(prompt, req.image_url, req.prompt_size, req.prompt_resolution)
            add_history(task_id=task_id, api_key_id=None, product_type=sanitize_input(req.product_type, 50),
                        country=sanitize_input(req.country, 20), model=model_code, status="completed", elapsed_seconds=round(time.time() - start, 1))
            return {"success": True, "data": {"detailImage": url}}

        if req.generate_type == "test":
            idx = max(0, min(req.style_index, 10))
            print(f"🧪 测试模式: 生成第 {idx+1}/11 张模特图...")
            gen_result = generate_all_tasks(
                req.product_type, req.image_url, req.country, req.model,
                req.prompt_size, req.prompt_resolution,
                category=category, country_config=country_config,
                model_code=model_code, model_profile=model_profile,
                llm_config=llm_config,
            )
            url = await apimart_generate(
                gen_result["tasks"][idx]["prompt"],
                gen_result["tasks"][idx]["reference_url"],
                req.prompt_size, req.prompt_resolution,
            )
            model_profile = gen_result["model_profile"]
            model_styles = [
                "时尚街拍风", "都市休闲风", "杂志大片风", "生活方式风",
                "自信站姿风", "活力户外风", "职业商务风", "海滩度假风",
                "艺术优雅风", "运动活力风", "奢华时尚风",
            ]
            tasks_detail = _build_tasks_detail(gen_result["tasks"], [url])
            add_history(task_id=task_id, api_key_id=None, product_type=sanitize_input(req.product_type, 50),
                        country=sanitize_input(req.country, 20), model=model_code, status="completed",
                        elapsed_seconds=round(time.time() - start, 1),
                        llm_request=llm_request_data, llm_response=llm_response_data,
                        tasks_detail=tasks_detail)
            return {
                "success": True,
                "data": {
                    "modelImages": [url],
                    "modelStyles": [model_styles[idx]],
                    "originalImage": req.image_url,
                    "category": gen_result["category"],
                    "model": model_profile,
                    "country": gen_result["country_config"],
                },
            }

        # 3. 全量生成模式
        gen_result = generate_all_tasks(
            req.product_type, req.image_url, req.country, req.model,
            req.prompt_size, req.prompt_resolution,
            category=category, country_config=country_config,
            model_code=model_code, model_profile=model_profile,
            llm_config=llm_config,
        )

        urls = await apimart_batch_generate(gen_result["tasks"], req.image_url)

        model_images = urls[:11]
        white_bg_url = urls[11]
        comparison_url = urls[12]
        detail_url = urls[13]

        elapsed = time.time() - start
        success_count = sum(1 for u in urls if u and not u.startswith("data:"))
        tasks_detail = _build_tasks_detail(gen_result["tasks"], urls)
        add_history(task_id=task_id, api_key_id=None, product_type=sanitize_input(req.product_type, 50),
                    country=sanitize_input(req.country, 20), model=model_code, total_images=14,
                    success_count=success_count, status="completed", elapsed_seconds=round(elapsed, 1),
                    llm_request=llm_request_data, llm_response=llm_response_data,
                    tasks_detail=tasks_detail)
        print(f"✅ 完成！总耗时 {elapsed:.1f}s")

        return {
            "success": True,
            "data": {
            "originalImage": req.image_url,
            "modelImages": model_images,
            "modelStyles": [
                "时尚街拍风", "都市休闲风", "杂志大片风", "生活方式风",
                "自信站姿风", "活力户外风", "职业商务风", "海滩度假风",
                "艺术优雅风", "运动活力风", "奢华时尚风",
            ],
            "displayImage": white_bg_url,
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
    except Exception as e:
        print(f"❌ 同步任务 {task_id} 失败: {e}")
        add_history(task_id=task_id, api_key_id=None, product_type=sanitize_input(req.product_type, 50),
                    country=sanitize_input(req.country, 20), model="", status="failed", error_msg=str(e)[:500])
        return {"success": False, "error": str(e)}


# ========== 异步进度端点 ==========

async def _run_generation_background(task_id: str, req: GenerateRequest):
    """后台执行完整的图片生成流程，并更新进度"""
    try:
        progress = task_store[task_id]
        progress["status"] = "submitting"

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
                    image_url=str(req.image_url) if req.image_url else None,
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
                    image_url=str(req.image_url) if req.image_url else None,
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
                    print(f"  🤖 LLM 分析成功: {len(llm_config.get('scene_config', {}).get('scenes', []))} 个场景, {len(llm_config.get('metadata', {}).get('titles', []))} 条标题")
            except Exception as e:
                print(f"  ⚠️ LLM 分析失败（降级至模板）: {e}")

        # 生成任务
        gen_result = generate_all_tasks(
            req.product_type, req.image_url,
            req.country, req.model,
            req.prompt_size, req.prompt_resolution,
            category=category,
            country_config=country_config,
            model_code=model_code,
            model_profile=model_profile,
            llm_config=llm_config,
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

        progress["status"] = "generating"
        save_task_progress(task_id, progress)

        # 批量生成
        urls = await apimart_batch_generate(
            gen_result["tasks"], req.image_url, on_progress
        )

        # 构建结果
        model_images = urls[:11]
        white_bg_url = urls[11]
        comparison_url = urls[12]
        detail_url = urls[13]

        model_profile = get_model_profile(model_code)

        progress["result"] = {
            "success": True,
            "data": {
                "originalImage": req.image_url,
                "modelImages": model_images,
                "modelStyles": [
                    "时尚街拍风", "都市休闲风", "杂志大片风", "生活方式风",
                    "自信站姿风", "活力户外风", "职业商务风", "海滩度假风",
                    "艺术优雅风", "运动活力风", "奢华时尚风",
                ],
                "displayImage": white_bg_url,
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
        print(f"✅ 后台任务 {task_id} 完成")

        # 写入历史记录
        tasks_detail_json = _build_tasks_detail(gen_result["tasks"], urls)
        add_history(
            task_id=task_id,
            api_key_id=None,
            product_type=sanitize_input(req.product_type, 50),
            country=sanitize_input(req.country, 20),
            model=model_code,
            prompt_size=req.prompt_size,
            prompt_resolution=req.prompt_resolution,
            total_images=14,
            success_count=progress["completed"],
            status="completed",
            elapsed_seconds=round(time.time() - progress["start_time"], 1),
            llm_request=llm_request_data,
            llm_response=llm_response_data,
            tasks_detail=tasks_detail_json,
        )

    except Exception as e:
        print(f"❌ 后台任务 {task_id} 失败: {e}")
        p = task_store.get(task_id)
        if p:
            p["status"] = "error"
            p["error"] = str(e)
            save_task_progress(task_id, p)
        add_history(
            task_id=task_id,
            api_key_id=None,
            product_type=sanitize_input(req.product_type, 50),
            country=sanitize_input(req.country, 20),
            model=sanitize_input(req.model, 20),
            status="failed",
            error_msg=str(e)[:500],
        )


@app.post("/api/generate/async")
@limiter.limit("20/minute")
async def generate_async(request: Request, req: GenerateRequest, _=Depends(verify_api_auth)):
    """异步启动图片生成，立即返回 task_id"""
    validate_image_data(str(req.image_url))
    client_ip = request.client.host if request.client else "unknown"
    task_id = init_progress(14, creator_ip=client_ip)
    asyncio.create_task(_run_generation_background(task_id, req))
    print(f"🚀 后台任务已启动: {task_id} (IP: {client_ip})")
    return {"task_id": task_id}


@app.get("/api/generate/status/{task_id}")
@limiter.limit("30/minute")
async def generate_status(request: Request, task_id: str, _=Depends(verify_api_auth)):
    """查询实时进度（仅允许任务创建者查询）"""
    p = task_store.get(task_id)
    if not p:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    client_ip = request.client.host if request.client else "unknown"
    if p.get("creator_ip") and p["creator_ip"] != "unknown" and p["creator_ip"] != client_ip:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

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


# ========== 自定义产品类型持久化 ==========


@app.get("/api/custom-types")
async def list_custom_types():
    return {"types": get_all_custom_types()}


@app.post("/api/custom-types")
@limiter.limit("30/minute")
async def create_custom_type(request: Request, body: dict):
    label = sanitize_input(body.get("label", ""), 100)
    category = sanitize_input(body.get("category", "自定义"), 50)
    if not label:
        raise HTTPException(status_code=400, detail="类型名称不能为空")
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
    """管理员登录 — 返回 JSON + 设置 HttpOnly Cookie"""
    username = sanitize_input(req.username, 50)
    result = await login(username, req.password)
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
    return {"username": user.get("sub"), "role": user.get("role")}


@app.post("/admin/refresh")
async def admin_refresh(user: dict = Depends(authenticate)):
    """刷新 token（延长有效期）"""
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
async def admin_logout():
    """登出 — 清除 cookie"""
    resp = JSONResponse(content={"message": "已登出"})
    resp.set_cookie(
        key="access_token",
        value="",
        httponly=True,
        samesite="lax",
        path="/",
        max_age=0,
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
async def list_api_keys(show_full: bool = False, user: dict = Depends(authenticate)):
    """列出所有 API Key（默认脱敏，show_full=true 返回完整 Key）"""
    if show_full:
        return {"keys": get_all_keys()}
    return {"keys": get_all_keys_masked()}


@app.post("/admin/api-keys")
@limiter.limit("10/minute")
async def create_api_key(request: Request, req: dict, user: dict = Depends(authenticate)):
    """添加 API Key"""
    key_value = sanitize_input(req.get("key_value", ""), 500)
    name = sanitize_input(req.get("name", ""), 100)
    daily_limit = req.get("daily_limit", 200)
    if not key_value:
        raise HTTPException(status_code=400, detail="Key 值不能为空")
    kid = add_key(key_value, name, int(daily_limit))
    return {"id": kid, "message": "Key 添加成功"}


@app.put("/admin/api-keys/{key_id}")
@limiter.limit("10/minute")
async def modify_api_key(request: Request, key_id: int, req: dict, user: dict = Depends(authenticate)):
    """更新 API Key"""
    kwargs = {}
    if "name" in req:
        kwargs["name"] = sanitize_input(req["name"], 100)
    if "is_active" in req:
        kwargs["is_active"] = int(req["is_active"])
    if "daily_limit" in req:
        kwargs["daily_limit"] = int(req["daily_limit"])
    ok = db_update_key(key_id, **kwargs)
    if not ok:
        raise HTTPException(status_code=404, detail="Key 不存在")
    return {"message": "更新成功"}


@app.delete("/admin/api-keys/{key_id}")
@limiter.limit("10/minute")
async def remove_api_key(request: Request, key_id: int, user: dict = Depends(authenticate)):
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

def mask_api_key(key: str) -> str:
    """脱敏显示 API Key，仅保留后 4 位"""
    if len(key) <= 8:
        return "****" + key[-4:]
    return key[:4] + "****" + key[-4:]


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
async def update_llm_config(request: Request, body: dict, user: dict = Depends(authenticate)):
    """更新 LLM 配置"""
    if "api_key" in body:
        val = body["api_key"].strip()
        if val:
            set_config("llm_api_key", val)
        else:
            from database import get_db
            get_db().execute("DELETE FROM system_config WHERE key = 'llm_api_key'")
            get_db().commit()
    if "model" in body:
        val = body["model"].strip()
        if val:
            set_config("llm_model", val)
    return {"message": "LLM 配置已更新"}


@app.post("/admin/llm-config/test")
@limiter.limit("5/minute")
async def test_llm_config(request: Request, body: dict, user: dict = Depends(authenticate)):
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
