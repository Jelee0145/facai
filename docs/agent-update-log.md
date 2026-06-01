# Agent Update Log

## 2026-06-01 — 延长图片生成轮询与 SSE 保活

### 任务目标

图片生成耗时可能明显长于数分钟，前端不能在后端仍在等待 Apimart 任务时自行放弃。任务应由后端终态驱动：拿到图片、上游明确失败、认证/额度等致命错误，或达到可配置的服务端总超时。

### 实现方案

1. `backend/main.py` 将单图和批量轮询从固定轮数改为 `APIMART_POLL_TIMEOUT_SECONDS` 控制的长轮询，默认 3600 秒。
2. 批量轮询不再因“若干轮没有完成新图片”提前终止；只要任务未终态就继续查询并发送心跳。
3. `backend/sse.py` 空闲时发送 SSE keep-alive comment，不再把 SSE 空闲当成任务 `timeout` 终态。
4. `GET /api/generate/status/{task_id}/stream` 连接建立时先发送当前任务快照，断线重连也能补到已完成结果。
5. `src/lib/use-sse.ts` 去掉 3 次重连后失败的前端判死逻辑，改为持续指数退避重连；只有后端终态或会话过期才结束。

### 变更文件

| 文件 | 说明 |
|---|---|
| `backend/main.py` | 长轮询配置、心跳、SSE 初始快照 |
| `backend/sse.py` | 空闲 keep-alive，不再发送 timeout 终态 |
| `src/lib/use-sse.ts` | 前端持续重连，等待后端终态 |
| `src/app/page.tsx` | 记录 heartbeat 中 processing/waiting 数量 |
| `.env.example`, `backend/.env.example` | 新增轮询保活配置 |
| `docs/agent-update-log.md` | 记录本次修复 |

---

## 2026-06-01 — 修复 Apimart task 查询误用 API Key 导致有效 Key 被禁用

### 任务目标

解决前端提交图片生成后短时间返回 502、后台提示 API Key 鉴权失败并自动禁用，但 Apimart 侧实际已经产图的问题。

### 问题根因

批量生成时每张图的提交请求会通过多 Key 轮询使用不同 API Key；但后续 `GET /tasks/{task_id}` 查询没有绑定创建该 task 的 Key，而是再次轮询取“下一个 Key”。如果 Apimart 的 task 查询按 Key/账号隔离，用 B Key 查询 A Key 创建的 task 会返回 401/403，旧逻辑随后把 B Key 记为鉴权失败，连续轮询后会把有效 Key 自动禁用。

### 实现方案

1. `_apimart_request` 支持返回本次实际使用的 API Key，并支持显式指定查询 Key。
2. `apimart_generate` / `_submit_task` 在提交成功时记录 `task_id -> api_key`。
3. `_query_single_task` 固定使用创建该 task 的 Key 查询，并且任务查询阶段的 401/403 不再计入 Key 鉴权失败。
4. 同一次请求内，同一把 Key 的 401/403 最多计一次失败，并且鉴权失败切换时只选择本次尚未尝试过的 Key。
5. 新增 `backend/apimart_key_binding_regression.py` 回归测试，覆盖单图和批量任务的 Key 绑定。

### 变更文件

| 文件 | 说明 |
|---|---|
| `backend/main.py` | 绑定 task 查询所用 Key，避免轮询查询误伤有效 Key |
| `backend/apimart_key_binding_regression.py` | 新增 Apimart task/key 归属回归测试 |
| `docs/agent-update-log.md` | 记录本次修复 |

### 检查项

- [x] Python 语法检查
- [x] Apimart Key 绑定回归测试

---

## 2026-05-27 — 修复 API Key 管理：精确错误消息 + 鉴权失败自动禁用

### 任务目标

解决"有额度的 Key 被错误禁用"和"生成失败时错误消息不明确"两个问题。

### 问题根因

1. `_apimart_request` 把 402（额度不足）和 401/403（鉴权失败）混在一起处理，都会触发 `mark_failure`，导致有额度的 Key 的 `fail_count` 被错误累加到 3 后自动禁用。
2. 网络异常（ConnectError 等）也会触发 `mark_failure`，网络抖动同样会导致 Key 被计为失败。
3. 错误消息过于笼统，无法区分鉴权失败、额度不足、网络异常等不同原因。

### 计划文件

- `backend/database.py` — `mark_key_failed` 函数
- `backend/main.py` — `_apimart_request`、`ensure_api_key_available` 函数

### 实现方案

#### 1. `backend/database.py` — 恢复自动禁用逻辑

在 `mark_key_failed` 中恢复阈值检查：`fail_count >= 3` 时自动 `is_active=0`。此逻辑之前被移除，现在恢复，但配合 `_apimart_request` 的改进，只有 401/403 鉴权失败才会触发。

#### 2. `backend/main.py` — `_apimart_request` 错误分类

| HTTP 状态码 | 处理方式 | 错误消息 |
|---|---|---|
| 200 | `mark_success`，返回结果 | — |
| 401/403 | `mark_failure` + 换 Key 重试 | 所有 Key 鉴权均失败，请到后台检查 Key 状态 |
| 402 | 不 `mark_failure`，直接报错 | Apimart API Key 额度不足或账号未开通 (402) |
| 其他 HTTP 错误 | 不 `mark_failure`，返回 apimart 原始消息 | 动态提取上游错误详情 |
| 网络异常 | 不 `mark_failure`，重试后报错 | 上游 API 网络连接失败，请稍后重试 |
| 无可用 Key | 直接报错 | 所有 API Key 均已失效，请到后台检查或添加新 Key |

#### 3. `backend/main.py` — `ensure_api_key_available` 消息优化

新增独立函数，返回更具体的提示：区分"没有 Key"和"所有 Key 被自动禁用"。

### 风险与回归分析

- **安全风险**：无新增权限或认证逻辑变更。
- **数据迁移**：无 schema 变更，`api_keys` 表结构不变。
- **缓存/状态**：Key 状态实时从 DB 读取，无缓存一致性问题。
- **构建影响**：纯后端逻辑变更，不影响前端构建。

### 变更文件

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `backend/database.py:322` | 修改 | `mark_key_failed` 恢复 `fail_count >= 3` 自动禁用 |
| `backend/main.py:91` | 新增 | `ensure_api_key_available()` 独立函数 |
| `backend/main.py:354` | 修改 | `_apimart_request` 错误分类与消息优化 |
| `backend/main.py:378-403` | 修改 | 401/403 单独处理、402 单独处理、网络异常不计数 |

### 检查项

- [x] 无效 Key 测试：收到"鉴权失败"错误，fail_count 递增，3 次后自动禁用
- [x] 有效 Key 测试：正常生成，不受 fail_count 影响
- [x] 网络异常测试：收到"网络连接失败"错误，Key 不被禁用
- [x] 全部 Key 禁用后：收到"所有 Key 均已失效"提示
- [x] 前后端启动验证：Backend 8001、Frontend 4524 均正常

### 后续工作

- 前端 Admin 面板的 Key 列表展示 `is_active` 为 INTEGER 可能被当作 truthy 显示为"启用"，需确认前端是否正确处理。
- 考虑增加 Key 的"冷却恢复"机制：被自动禁用的 Key 经过一段时间后自动重新启用。

---

## 2026-05-27 — 修复 apimart 图片生成请求失败 + 前端 SSE 锁定

### 任务目标

解决"apimart 后台显示请求无状态"、"轮询不启动"、"前端永久锁定"三个关联问题。

### 问题根因

1. **根本原因**: apimart.ai 已不再支持在 `image_urls` 中直接传递 base64 data URL。必须先通过 `POST /v1/uploads/images` 上传图片获取 hosted URL。当前代码直接把用户上传的几 MB base64 塞进每个生成请求 → apimart 接受请求但无法处理 → 任务卡在 `submitted` 状态。
2. **轮询缺陷**: `_query_single_task` 只处理 `completed`/`failed` 两种状态，`pending`/`processing`/`cancelled` 全返回 None。`HTTPException`（402 余额不足等）被 `except Exception: return None` 静默吞掉 → 前端 SSE 永远收不到失败通知。
3. **前端缺陷**: SSE `onerror` 直接报 "Connection lost" 关闭连接，没有重连机制。网络抖动会导致前端直接锁定。

### 计划文件

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `backend/main.py` | 新增函数 | `apimart_upload_image()` — base64→上传→hosted URL |
| `backend/main.py` | 修改函数 | `_run_generation_background()` — 异步路径先上传再生成 |
| `backend/main.py` | 修改函数 | `generate_images()` — 同步路径先上传再生成 |
| `backend/main.py` | 重写函数 | `_query_single_task()` — 区分 5 种状态 + 错误分级 |
| `backend/main.py` | 重写函数 | `apimart_batch_generate()` — 早失败 + 超时保护 |
| `src/lib/use-sse.ts` | 重写 | 添加自动重连（最多 3 次，间隔 5s） |

### 实现方案

#### Step 1: 新增 `apimart_upload_image` 函数

**位置**: `backend/main.py`，`_apimart_request` 函数之后（约 L404）

```python
async def apimart_upload_image(image_url: str) -> str:
    """将 base64 图片上传到 apimart，返回 hosted URL (72h 有效)。
    如果已经是 HTTP URL，直接返回。"""
    if image_url.startswith("http://") or image_url.startswith("https://"):
        return image_url

    import base64  # ← 改为文件顶部导入
    m = DATA_URL_PATTERN.match(image_url)
    if not m:
        raise HTTPException(status_code=400, detail="图片格式无效")
    mime = m.group(1)
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

    return resp.json()["url"]
```

**注意**: `import base64` 放在文件顶部 `import json` 附近。

#### Step 2: 异步路径 `_run_generation_background` 调用上传

**位置**: `progress["status"] = "submitting"` 之后、品类匹配之前（约 L906）

插入:
```python
        hosted_image_url = await apimart_upload_image(req.image_url)
```

替换后续所有 `req.image_url` 为 `hosted_image_url`:
- `generate_all_tasks(...)` 调用 (约 L948) — 传入 `hosted_image_url`
- `apimart_batch_generate(gen_result["tasks"], hosted_image_url, on_progress)` (约 L988)

#### Step 3: 同步路径 `generate_images` 调用上传

**位置**: `try` 块中品类匹配之前（约 L706）

插入:
```python
        hosted_image_url = await apimart_upload_image(str(req.image_url))
```

替换后续所有 `req.image_url` / `str(req.image_url)` 为 `hosted_image_url`:
- `apimart_generate(prompt, hosted_image_url, ...)` — L753, L764, L782
- `generate_all_tasks(... hosted_image_url ...)` — L775, L814
- `apimart_batch_generate(gen_result["tasks"], hosted_image_url)` — L822
- 返回结果中的 `"originalImage": hosted_image_url` — L800

#### Step 4: 重写 `_query_single_task`

**位置**: L552-563，完全替换

```python
async def _query_single_task(task_id: str) -> str | dict:
    """查询单个任务状态。
    返回:
      str (URL) — completed
      "failed" — failed/cancelled
      dict {"status": ..., "progress": ...} — pending/processing
    异常:
      HTTPException — 不可重试的致命错误 (由 _apimart_request 抛出)
    """
    try:
        task = await _apimart_request(f"{APIMART_BASE}/tasks/{task_id}", "GET")
        data = task.get("data", {})
        status = data.get("status")

        if status == "completed":
            try:
                return data["result"]["images"][0]["url"][0]
            except (KeyError, IndexError):
                return "failed"

        if status in ("failed", "cancelled"):
            error_msg = data.get("error", {}).get("message", "未知错误")
            print(f"  [WARN] Task {task_id} {status}: {error_msg}")
            return "failed"

        return {"status": status, "progress": data.get("progress", 0)}

    except HTTPException:
        raise
    except Exception as e:
        print(f"  [WARN] Query task {task_id} error: {e}")
        return None
```

#### Step 5: 重写 `apimart_batch_generate` 轮询逻辑

**关键改进**:
- 初始等待 12s → 15s
- 捕获 `HTTPException` 致命错误（402 等）→ 立即终止整个批量任务
- 连续 5 轮无进展 → 提前终止（不再等满 120s）
- 每轮打印进度日志
- 未完成的任务用 fallback URL 填充

#### Step 6: 前端 `use-sse.ts` 自动重连

**关键改进**:
- 断连后自动重连，最多 3 次，间隔 5s
- 收到任何有效消息后重置重连计数
- `closed` 标志防止组件卸载后继续重连
- 超过重连次数才报 "Connection lost"

### 风险与回归分析

- **安全风险**: 上传函数使用已有的 `_apimart_request` 链路中的 Key 管理，无新增权限风险
- **数据迁移**: 无 schema 变更
- **缓存/状态**: 无新增缓存
- **构建影响**: 后端 Python 改动 + 前端 `use-sse.ts` 改动，需验证 `pnpm lint` + `pnpm ts-check`
- **性能影响**: 每次生成多一次上传请求（~1-2s），但仅对 base64 图片生效；已是 HTTP URL 的零开销
- **回归风险**: `_query_single_task` 返回值类型从 `str | None` 变为 `str | dict | None`，`apimart_batch_generate` 中的判断逻辑需同步更新

### 检查项

- [ ] `pnpm lint` 通过
- [ ] `pnpm ts-check` 通过
- [ ] 前后端启动验证：Backend 8001、Frontend 4524 均正常

### 实施结果

#### 变更文件

| 文件 | 变更类型 | 说明 |
|---|---|---|
| `backend/main.py:8` | 新增 | `import base64` — 顶部导入 |
| `backend/main.py:407-440` | 新增 | `apimart_upload_image()` 函数 — base64→上传→hosted URL |
| `backend/main.py:443-481` | 重写 | `apimart_generate()` — 使用 `_query_single_task` 统一轮询，等待 12s→15s |
| `backend/main.py:484-597` | 重写 | `apimart_batch_generate()` — 早失败(5轮无进展终止)、致命错误(402)立即终止 |
| `backend/main.py:602-637` | 重写 | `_query_single_task()` — 区分5种状态、错误分级、不再静默吞异常 |
| `backend/main.py:744` | 新增 | 同步路径调用 `apimart_upload_image` |
| `backend/main.py:792,803,815,854,861,841,883` | 修改 | 同步路径 7 处 `req.image_url` → `hosted_image_url` |
| `backend/main.py:947` | 新增 | 异步路径调用 `apimart_upload_image` |
| `backend/main.py:988,1028,1042` | 修改 | 异步路径 3 处 `req.image_url` → `hosted_image_url` |
| `src/lib/use-sse.ts` | 重写 | 自动重连机制（最多3次，间隔5s） |

#### 检查结果

- [x] `pnpm lint` — 0 errors, 13 warnings (均为预存警告，与本次改动无关)
- [x] `pnpm ts-check` — 通过
- [x] Python 语法检查 — 通过
