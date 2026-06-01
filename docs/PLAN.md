# 计费与认证安全修复计划

## Summary

本计划修复当前审计文档中已确认的计费、认证、SSE 和代理问题，并对两项被高估的问题降级为一致性/防误用修复。核心目标是：失败任务必定进入终态、退款账本一致、首次部署可创建 admin、登录失败锁定语义一致、内部 API 认证不再隐式空 token 放行、SSE 断线能给出可理解错误。

## 根因判断与涉及文件

| 问题 | 根因 | 涉及文件 | 修复定性 |
|---|---|---|---|
| 新部署 admin 不存在 | `startup()` 只建表不建账号，`seed.py` 未被启动路径调用 | `backend/main.py`, `backend/seed.py` | 部署阻断，优先修 |
| 退款失败导致任务卡住 | 异常处理块内先退款，退款异常会跳过状态落库和 SSE 终态 | `backend/main.py`, `backend/database.py` | P0 |
| 不存在用户名不锁定 | 失败计数只写 `users` 行，不存在用户更新 0 行 | `backend/security.py`, `backend/database.py` | P1 |
| 无限额度用户退款虚增账本 | 消费记 0，但失败退款仍按固定 `charge_points` 加回 | `backend/database.py`, `backend/main.py` | P1 |
| SSE 认证后无法区分会话过期 | `EventSource.onerror` 拿不到 401 状态，只盲重试 | `src/lib/use-sse.ts` | P2 |
| admin logout 缺 `secure` | 删除 cookie 属性与设置 cookie 不一致；不是已确认绕过，但应修一致性 | `backend/main.py`, `backend/test_security.py` | P2 降级 |
| `forwardCookies` 死代码 | true/false 分支都转发 cookie | `src/lib/proxy.ts` | P3 |
| 空 `API_AUTH_TOKEN` 隐式通过 | 空请求头与空配置相等，开发环境变成静默放行 | `backend/main.py`, `backend/test_security.py` | P3 但建议修 |

## 分阶段修改步骤

### Phase 1: 退款与任务终态先修

| 步骤 | 具体操作 |
|---|---|
| 1.1 | 在 `backend/main.py` 增加一个小 helper，例如 `_try_refund_generation(task_data, user_id, task_id, points, reason) -> dict`，内部 `try/except` 调用 `ensure_refund_once`，失败时只记录 `logger.exception`，并把 `task_data["refund_status"] = "failed"`、`task_data["refund_error"] = str(err)[:500]`。 |
| 1.2 | 在 `_run_generation_background()` 的 `except Exception` 分支中先调用 `_try_refund_generation()`，无论退款是否成功都继续设置 `p["status"] = "error"`、`p["error"] = str(e)`、`save_task_progress()`、`push_event(... failed ...)`、`add_history(status="failed")`。 |
| 1.3 | 在 startup reaper 的 stale task 处理里也使用 `_try_refund_generation()`，避免一个退款异常导致本轮 stale task 后续状态更新全部跳过。 |
| 1.4 | 检查同步 `/api/generate` 的两个异常分支，目前也直接调用 `ensure_refund_once()`；同样改成 `_try_refund_generation()`，避免同步请求因退款异常覆盖原始错误处理。 |
| 1.5 | 在 `backend/database.py` 修改 `refund_generation()`：开始事务后先查 `users.is_unlimited`，如果是无限额度用户，直接返回 `{"status": "skipped_unlimited", "refunded": False, "points": 0, "reason": "unlimited_user"}`，不更新钱包、不插入 refund 账本。 |
| 1.6 | 修改 `ensure_refund_once()` 的 `task_data["refunded"]` 判定，使 `skipped_unlimited` 也被视为已处理，避免重复尝试无限用户退款。 |
| 1.7 | 保持 `charge_generation()` 对无限用户消费记 0 的行为不变，避免改变现有账本展示，只修退款路径。 |

### Phase 2: 登录锁定、admin 初始化、内部认证

| 步骤 | 具体操作 |
|---|---|
| 2.1 | 在 `backend/database.py:init_db()` 新增表 `customer_login_attempts(username TEXT PRIMARY KEY, login_attempts INTEGER DEFAULT 0, locked_until TEXT, updated_at TEXT DEFAULT (datetime('now')))`，用于记录不存在用户的失败尝试。 |
| 2.2 | 增加 `get_customer_login_lock(username: str) -> dict | None`，返回该用户名在 `customer_login_attempts` 或 `users.locked_until` 中更晚的锁定时间。 |
| 2.3 | 重写 `record_customer_login_attempt(username, success)`：成功时清空 `customer_login_attempts` 对应行并重置真实用户字段；失败时对 `customer_login_attempts` 做 upsert 自增，达到 5 次后写入 15 分钟 `locked_until`，如果真实用户存在也同步写 `users.locked_until`。 |
| 2.4 | 在 `backend/security.py:login_customer()` 开头先调用 `get_customer_login_lock()`；如果锁定时间未过，直接返回 429；然后再查用户、检查状态、校验密码、记录成功或失败。 |
| 2.5 | 在 `backend/main.py:startup()` 的 `init_db()` 后增加 admin bootstrap：如果 `get_user("admin")` 不存在且 `ADMIN_PASSWORD` 有值，则用 `hash_password(ADMIN_PASSWORD)` 创建 admin；如果生产环境 admin 不存在且 `ADMIN_PASSWORD` 为空或弱密码，则打印安全错误并 `sys.exit(1)`；开发环境为空只打印明确提示，不生成也不打印随机密码。 |
| 2.6 | 在 `backend/seed.py` 删除 `print(f"[SEED] Password: {seed_password}")`，保留“已写入 backend/.env / 已创建 admin”的状态日志，避免容器或 CI 日志泄露明文密码。 |
| 2.7 | 在 `backend/main.py:verify_api_auth()` 改成显式配置语义：`API_AUTH_TOKEN` 为空时返回 503 `API auth is not configured`；非空时用 `hmac.compare_digest(auth_header, API_AUTH_TOKEN)` 比较。 |
| 2.8 | 确认生产启动保护仍保留：`NODE_ENV=production` 且 `API_AUTH_TOKEN` 为空必须启动失败。 |

### Phase 3: 前端 SSE、代理和 cookie 一致性

| 步骤 | 具体操作 |
|---|---|
| 3.1 | 在 `src/lib/use-sse.ts` 把 `source.onerror` 改为可调用异步检查的实现：达到 `MAX_RECONNECT` 后 `fetch("/api/auth/me", { credentials: "include" })`，如果返回 JSON 中 `user` 为空，则调用 `onError("会话已过期，请重新登录")` 并关闭连接。 |
| 3.2 | 如果 `/api/auth/me` 请求失败或仍有 user，则保持原有错误 `"Connection lost after retries"`，避免把网络失败误报成登录过期。 |
| 3.3 | 在 `src/lib/proxy.ts` 修改 `forwardCookies=false` 分支，过滤 `cookie` 头；保留 `forwardCookies=true` 分支继续转发 cookie；两边都继续过滤 `host`、`content-length`、`transfer-encoding`、`expect`。 |
| 3.4 | 在 `backend/main.py:admin_logout()` 的 `set_cookie()` 增加 `secure=COOKIE_SECURE`，作为和 login/refresh 对齐的一致性修复。 |
| 3.5 | 不改公开 API 路径和响应主结构；唯一用户可见变化是 SSE 断线后可能显示“会话已过期，请重新登录”。 |

### Phase 4: 回归测试补齐

| 测试文件 | 具体新增/修改 |
|---|---|
| `backend/test_refund_idempotency.py` | 新增无限额度用户场景：设置 `users.is_unlimited=1`，调用 `charge_generation(..., 10)` 后 `ensure_refund_once(..., 10)`，断言退款状态为 `skipped_unlimited`，refund 账本数量为 0，钱包余额不增加。 |
| `backend/test_task_store.py` 或新建 `backend/test_refund_failure_terminal_state.py` | 新增 helper 级测试：monkeypatch `main.ensure_refund_once` 抛异常，调用失败标记 helper，断言任务状态仍为 `error`、保存函数被调用、SSE failed 事件被推送、`refund_status` 为 `failed`。 |
| `backend/test_security.py` | 更新 `2.3 /api/generate rejects missing internal API auth`：当 `API_AUTH_TOKEN` 为空时预期 503；当非空时缺 header 预期 403。更新 logout 测试，断言 `Set-Cookie` 包含 `max-age=0`，如果 `COOKIE_SECURE=true` 则包含 `Secure`。 |
| 新建或扩展后端单测 | 增加不存在用户登录失败锁定测试：临时 DB 下连续 5 次 `record_customer_login_attempt("__missing__", False)` 后 `get_customer_login_lock("__missing__")` 返回未来时间；成功记录会清空对应锁定。 |
| 前端检查 | 不需要新增浏览器测试；依靠 `pnpm ts-check` 覆盖 `useSSE` 类型变更，依靠 `pnpm lint` 覆盖 hook 代码质量。 |

## 自测方法

| 阶段 | 命令 |
|---|---|
| 静态编译 | `.\backend\.venv\Scripts\python.exe -m py_compile .\backend\main.py .\backend\database.py .\backend\security.py .\backend\seed.py` |
| 后端单测 | `.\backend\.venv\Scripts\python.exe .\backend\test_refund_idempotency.py` |
| 后端任务存储 | `.\backend\.venv\Scripts\python.exe .\backend\test_task_store.py` |
| 新增安全单测 | `.\backend\.venv\Scripts\python.exe .\backend\test_refund_failure_terminal_state.py`，如果采用扩展现有文件则运行对应文件 |
| 前端类型 | `pnpm ts-check` |
| 前端 lint | `pnpm lint` |
| 安全验收服务启动 | 在单独终端执行 `cd D:\project\projects\backend; .\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8001` |
| 安全验收脚本 | 服务启动后执行 `$env:TEST_BASE="http://127.0.0.1:8001"; .\backend\.venv\Scripts\python.exe .\backend\test_security.py` |

所有测试都必须避免发送有效图片生成请求；`test_security.py` 只允许覆盖健康检查、认证、CORS、缺 token、无效 payload 和 4xx 路径。

## 风险点

| 风险 | 控制措施 |
|---|---|
| admin 自动创建可能使用弱密码 | 生产环境弱 `ADMIN_PASSWORD` 直接启动失败；开发环境只告警。 |
| `API_AUTH_TOKEN` 为空改为 503 可能影响本地开发 | 这是预期安全变化；本地需要在 `.env` 和 `backend/.env` 配置一致 token，Next 代理会继续自动加 `X-API-Auth`。 |
| 新登录失败表引入旧数据兼容问题 | 使用 `CREATE TABLE IF NOT EXISTS`，不迁移删除旧字段；真实用户的 `users.login_attempts/locked_until` 继续同步维护。 |
| 退款异常被吞可能隐藏账务问题 | 只吞掉退款异常以保证任务终态，同时必须 `logger.exception` 并写入 `refund_status/refund_error`，便于后续排查和人工补偿。 |
| SSE 断线误判会话过期 | 只有 `/api/auth/me` 成功返回 `user: null` 才提示会话过期，其余情况保持原错误。 |
| `secure` cookie 删除测试受环境变量影响 | 测试根据 `COOKIE_SECURE` 条件断言，不强制所有环境都出现 `Secure`。 |

## 验收标准

| 验收项 | 标准 |
|---|---|
| 失败任务终态 | 即使退款函数抛异常，任务也必须落库为 `error`，SSE 必须推送 `failed`，历史记录必须写入 failed。 |
| 无限用户退款 | 无限用户生成失败不增加钱包余额，不产生 `refund` 入账记录，任务标记为退款已处理或跳过。 |
| 不存在用户名锁定 | 不存在用户名连续失败达到阈值后返回与真实用户一致的锁定行为，不能通过锁定差异判断用户名是否存在。 |
| 首次部署 admin | `ADMIN_PASSWORD` 存在且 admin 不存在时，启动后可创建 admin；生产环境缺失或弱密码时明确失败，不打印明文密码。 |
| 内部 API 认证 | `API_AUTH_TOKEN` 为空时生成端点返回 503；配置后缺失或错误 header 返回 403；正确 header 继续进入后续业务校验。 |
| SSE 用户体验 | 会话丢失后重连失败显示“会话已过期，请重新登录”；普通网络断线仍显示原连接失败信息。 |
| 代理安全 | `forwardCookies=false` 时不再转发 `cookie` 头；现有 admin/auth/user/generate 代理继续显式 `forwardCookies=true`。 |
| 回归测试 | `py_compile`、后端单测、`pnpm ts-check`、`pnpm lint`、运行中后端的 `test_security.py` 全部通过。 |
