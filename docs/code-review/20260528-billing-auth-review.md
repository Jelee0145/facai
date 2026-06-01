# 代码审查：用户认证与计费系统

**审查日期**：2026-05-28
**审查范围**：未提交的更改（17 个文件，约 1800 行新增）
**审查级别**：high（三角度扫描 + 逐一验证）
**涉及功能**：前台用户认证、积分/充值/订单系统、SSE 重连优化、admin 安全加固

---

## 发现汇总

| # | 优先级 | 文件 | 状态 |
|---|--------|------|------|
| 1 | P0 | backend/main.py:173 | CONFIRMED |
| 2 | P0 | backend/main.py:1135 | CONFIRMED |
| 3 | P1 | backend/security.py:131 | CONFIRMED |
| 4 | P1 | backend/database.py:748 | CONFIRMED |
| 5 | P2 | backend/main.py:1208 | CONFIRMED |
| 6 | P2 | backend/main.py:1316 | CONFIRMED |
| 7 | P3 | src/lib/proxy.ts:77 | PLAUSIBLE |
| 8 | P3 | backend/main.py:112 | PLAUSIBLE |

---

## 1. [P0] 管理员账号不会自动创建 — seed.py 无人调用

**文件**：`backend/main.py`，startup 函数（第 173 行起）

### 问题

旧代码在 `@app.on_event("startup")` 里自动创建 admin 用户：

```python
# 旧代码（已删除）
admin_pw = os.getenv("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
if not get_user("admin"):
    create_user("admin", hash_password(admin_pw))
```

新代码将这段逻辑移到了 `seed.py`，但没有任何自动部署路径调用 `seed.py`：

- `main.py` 的 startup 函数 → 未调用
- `scripts/start-all.sh` → 未调用
- `scripts/up.ps1` → 未调用
- Dockerfile → 未调用

`main.py` 的 startup 调用了 `init_db()`，它会创建数据库**表**，但不会往 `admin_users` 表里**插入行**。

### 后果

全新部署时，管理后台登录永远返回 401，无任何错误提示。运维人员必须手动发现并运行 `python seed.py`，但没有文档或启动日志提醒他们这样做。

### 修复方案

在 startup 函数中加回自动创建 admin 的逻辑：

```python
# 在 main.py 的 startup() 中 init_db() 之后加入：
import secrets as _secrets
from database import get_user, create_user as _create_admin_user
from security import hash_password as _hash_pw

admin_pw = os.getenv("ADMIN_PASSWORD", "")
if not admin_pw:
    admin_pw = _secrets.token_urlsafe(16)
if not get_user("admin"):
    _create_admin_user("admin", _hash_pw(admin_pw))
    print(f"[INIT] Admin account created. Password: {admin_pw}")
    # 可选：写入 .env
```

或者在 `start-all.sh` 和 Dockerfile CMD 中加入 `python seed.py` 调用。

---

## 2. [P0] 后台任务退款失败时，任务永久卡在 "generating"

**文件**：`backend/main.py`，`_run_generation_background` 异常处理块（第 1129–1152 行）

### 问题

```python
except Exception as e:
    p = task_store.get(task_id)
    if p:
        # ⚠️ 如果这里抛异常，后续代码全部跳过
        ensure_refund_once(p, user_id_val, task_id, charge_val, "生成失败自动退回")
        p["status"] = "error"          # ← 永远不执行
        save_task_progress(task_id, p) # ← 永远不执行
        push_event(task_id, {"status": "failed", "error": str(e)})  # ← 永远不执行
```

`ensure_refund_once` → `refund_generation` 在数据库异常时会 `raise`。如果数据库被锁或磁盘满，异常会从 `except` 块传播出去。

### 后果

- `p["status"]` 停留在 `"generating"`
- 前端 SSE 流永远收不到终态事件
- 用户看到无限加载动画，直到 5 分钟后 reaper 才兜底
- 积分已扣但用户完全不知情

### 修复方案

用独立 try/except 包裹退款逻辑：

```python
except Exception as e:
    p = task_store.get(task_id)
    if p:
        try:
            ensure_refund_once(p, p.get("user_id", user_id), task_id,
                               p.get("charge_points", charge_points), "生成失败自动退回")
        except Exception as refund_err:
            logger.error(f"[ERROR] Refund failed for task {task_id}: {refund_err}")
        p["status"] = "error"
        p["error"] = str(e)
        save_task_progress(task_id, p)
        push_event(task_id, {"status": "failed", "error": str(e)})
    else:
        try:
            ensure_refund_once({}, user_id, task_id, charge_points, "生成失败自动退回")
        except Exception as refund_err:
            logger.error(f"[ERROR] Refund failed for task {task_id}: {refund_err}")
    # add_history ...
```

同样的问题也存在于 reaper（第 220–235 行），也需要加 try/except。

---

## 3. [P1] 登录锁定对不存在的用户名无效

**文件**：`backend/security.py:131`，调用 `backend/database.py:521–538`

### 问题

```python
# security.py line 131-133
if not user or user.get("status") != "active":
    record_customer_login_attempt(username, success=False)  # ← 对不存在用户无效
    raise HTTPException(status_code=401, detail="用户名或密码错误")
```

```python
# database.py record_customer_login_attempt
db.execute("UPDATE users SET login_attempts = login_attempts + 1 WHERE username = ?", (username,))
# ↑ 用户名不存在时更新 0 行
row = db.execute("SELECT login_attempts FROM users WHERE username = ?", (username,)).fetchone()
# ↑ 返回 None
if row and row["login_attempts"] >= 5:  # ← row is None，永远不触发
```

### 后果

1. **用户名枚举**：对真实用户触发锁定，对虚假用户名不触发 → 攻击者可区分用户名是否存在
2. **无限暴力破解**：对不存在的用户名，攻击者可以 10次/分钟 的速率永不被锁定

### 修复方案

**方案 A**（推荐）：使用 IP 地址作为锁定 key，而非用户名：

```python
def record_customer_login_attempt(username: str, success: bool, client_ip: str = ""):
    db = get_db()
    lock_key = username  # 默认仍用用户名
    if not db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        lock_key = client_ip or username  # 用户名不存在时用 IP
    # ... 其余逻辑不变，但用 lock_key 查询
```

**方案 B**（简单）：对不存在用户名也插入一条临时记录，或维护一个独立的 IP 失败计数表。

---

## 4. [P1] 无限额度用户退款产生虚假账本记录

**文件**：`backend/database.py`，`charge_generation`（第 748 行）和 `refund_generation`（第 810 行）

### 问题

```python
# charge_generation — 无限用户记 0 分
if user and user["is_unlimited"]:
    db.execute("INSERT INTO user_ledger ... VALUES (?, 'consume', 'out', 0, 999999999, ?, ?)")
    # points = 0
```

```python
# 但调用方传入 charge_points = 10（正常价格）
charge_generation(user_id, task_id, charge_points=10, ...)
```

退款时：

```python
# refund_generation 传入 points=10
# 没有检查无限用户，直接：new_balance = 999999999 + 10 = 1000000009
# 账本记录：refund, points=10
```

### 后果

- 账本显示「消费 0，退回 10」，数据不一致
- 隐藏余额每次失败 +10（虽被 `get_wallet` 掩盖）
- 若 `is_unlimited` 后被撤销，用户余额虚高

### 修复方案

在 `ensure_refund_once` 或 `refund_generation` 开头检查无限用户：

```python
def ensure_refund_once(task_data, user_id, task_id, points, remark=""):
    from database import get_customer_by_id
    user = get_customer_by_id(user_id)
    if user and user.get("is_unlimited"):
        task_data["refunded"] = True
        task_data["refund_status"] = "skipped_unlimited"
        return {"status": "skipped_unlimited", "refunded": False, "points": 0}
    # ... 正常退款逻辑
```

或者让 `charge_generation` 对无限用户也返回实际扣除值（0），调用方用返回值而非固定值做退款。

---

## 5. [P2] SSE 流端点新增认证 — 会话丢失后无法重连

**文件**：`backend/main.py:1208`，`src/lib/use-sse.ts`

### 问题

旧的 SSE 端点不需要用户认证，新代码加了 `Depends(authenticate_customer)`。

EventSource（浏览器原生 API）不支持自定义请求头，只能靠 cookie 认证。如果在长任务期间：

- 用户在另一个标签页退出登录（cookie 被清除）
- JWT 过期
- 浏览器长时间后台挂起后 SSE 断开

重连时后端返回 401，但 JS 的 `onerror` 无法获取 HTTP 状态码，会盲目重试 3 次（每次等 5 秒），最终显示"Connection lost after retries"。

### 后果

任务实际完成、积分已扣，但用户看不到结果，只能手动刷新页面查看历史记录。

### 修复方案

SSE 重连失败后，轮询检测会话状态：

```typescript
// use-sse.ts onerror 中：
if (reconnectCount >= MAX_RECONNECT) {
  // 检查是否是会话过期
  try {
    const meRes = await fetch("/api/auth/me");
    if (meRes.ok) {
      const meData = await meRes.json();
      if (!meData.user) {
        handlersRef.current.onError?.("会话已过期，请重新登录");
        closed = true;
        return;
      }
    }
  } catch {}
  handlersRef.current.onError?.("Connection lost after retries");
  closed = true;
}
```

注意：`onerror` 目前不是 async 函数，需要改为 `async`。

---

## 6. [P2] admin_logout 清除 cookie 时缺少 secure 标志

**文件**：`backend/main.py:1316–1323`

### 问题

```python
# admin_login (line 1268) ✅
resp.set_cookie(key="access_token", ..., secure=COOKIE_SECURE)

# admin_refresh (line 1300) ✅
resp.set_cookie(key="access_token", ..., secure=COOKIE_SECURE)

# admin_logout (line 1316) ❌ 缺少 secure
resp.set_cookie(key="access_token", value="", httponly=True,
                samesite="lax", path="/", max_age=0)
# 没有 secure=COOKIE_SECURE
```

浏览器要求 Set-Cookie 的属性必须完全匹配才能删除 cookie。

### 后果

HTTPS + `COOKIE_SECURE=true` 部署时，退出登录实际上不清除 cookie。用户以为登出了，但 `access_token` cookie 仍然有效，可以继续访问管理后台。

### 修复方案

```python
resp.set_cookie(
    key="access_token",
    value="",
    httponly=True,
    samesite="lax",
    path="/",
    max_age=0,
    secure=COOKIE_SECURE,  # ← 加上这一行
)
```

---

## 7. [P3] proxy.ts 的 forwardCookies 分支是死代码

**文件**：`src/lib/proxy.ts:77–92`

### 问题

```typescript
if (forwardCookies) {
  request.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (k !== "host" && k !== "content-length" && ...) { headers[key] = value; }
  });
} else {
  // ⚠️ 和 if 分支完全相同的代码
  request.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (k !== "host" && k !== "content-length" && ...) { headers[key] = value; }
  });
}
```

两个分支逻辑完全一样。`forwardCookies` 标志没有任何实际效果。

### 后果

当前所有调用方都传 `forwardCookies: true`，不影响功能。但如果未来新增路由时不传该参数，cookie 仍然会被转发，可能导致认证状态泄漏。

### 修复方案

`else` 分支应过滤掉 `cookie` 头：

```typescript
} else {
  request.headers.forEach((value, key) => {
    const k = key.toLowerCase();
    if (k !== "host" && k !== "content-length" && k !== "transfer-encoding"
        && k !== "expect" && k !== "cookie") {
      headers[key] = value;
    }
  });
}
```

---

## 8. [P3] verify_api_auth 删掉了开发模式的显式跳过

**文件**：`backend/main.py:112–117`

### 问题

```python
# 旧代码
async def verify_api_auth(request: Request):
    if not API_AUTH_TOKEN:   # ← 开发模式显式跳过
        return True
    ...

# 新代码（删掉了上面的 if）
async def verify_api_auth(request: Request):
    auth_header = request.headers.get("X-API-Auth", "")
    if auth_header != API_AUTH_TOKEN:  # 依赖 "" != "" 为 False
        raise HTTPException(status_code=403, detail="Forbidden")
```

开发环境下前后端 `API_AUTH_TOKEN` 都为空字符串，`"" != ""` 为 False，能通过。但这是隐式依赖，不够健壮。

### 后果

- 如果只在一端设置了 `API_AUTH_TOKEN`，另一端为空 → 所有 `/api/generate` 请求返回 403
- 如果反向代理注入了默认的 `X-API-Auth` 头 → 同样全部 403

### 修复方案

恢复显式跳过，或在空值时打印警告：

```python
async def verify_api_auth(request: Request):
    if not API_AUTH_TOKEN:
        return  # 开发模式，无 token 则跳过
    auth_header = request.headers.get("X-API-Auth", "")
    if auth_header != API_AUTH_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True
```

---

## 附注：其他观察（非 Bug）

| 项目 | 说明 |
|------|------|
| `.env.example` 新增测试账号变量 | `ENABLE_TEST_ADMIN`、`TEST_USER_PASSWORD` 等在 `.env.example` 中定义，但 `seed.py` 和 `main.py` 均未读取，属于占位符 |
| `admin_update_generation_cost` 使用裸 dict | 其他 admin 端点已升级为 Pydantic model，此端点仍用 `req: dict`，`int(req.get("points", 10))` 对非法输入会抛 ValueError（FastAPI 会返回 422，不会崩溃，但风格不一致）|
| CSRF token 为静态 JTI | 登录后整个会话使用同一个 CSRF token（JWT 的 jti 字段），不会轮换。安全性低于逐请求 token，但因 token 仅通过认证端点暴露，风险可控 |
| `seed.py` 将密码打印到 stdout | `print(f"[SEED] Password: {seed_password}")` — CI/容器日志中会暴露明文密码 |
