# 安全升级方案文档

## 架构总览

```
┌─────────────────────────────────────────────────────┐
│  浏览器                                               │
│  Cookie: access_token (HttpOnly, SameSite=Lax, 7天)  │
└──────────┬──────────────────────────────────────────┘
           │
           ▼
┌──────────────────────┐     ┌──────────────────────┐
│  Next.js (port 5000)  │────▶│  FastAPI (port 8001)  │
│  - middleware.ts      │     │  - security.py        │
│  - CSP + 安全 Headers  │     │  - main.py            │
│  - API 代理转发       │     │  - database.py        │
│  - auth-context.tsx   │     │  - key_manager.py     │
└──────────────────────┘     └──────────────────────┘
```

- 前端 `/api/admin/*` 通过 Next.js Route Handler 代理到 FastAPI
- 认证凭证为 HttpOnly Cookie，由后端设置、浏览器自动携带
- 前后端之间的代理层负责转发 `Set-Cookie` 头

---

## Phase 1 — HttpOnly Cookie 认证迁移 [✅ 完成]

### 目标

将管理后台认证从 `localStorage + Authorization: Bearer` 迁移到 `HttpOnly Cookie`，同时将 JWT 过期从 30 分钟延长到 7 天。

### 改动清单

| # | 文件 | 改动内容 | 状态 |
|---|------|----------|------|
| 1.1 | `backend/security.py` | `authenticate` 同时支持 Header 和 Cookie；`create_token` 支持 7 天；启动时校验 JWT_SECRET | ✅ |
| 1.2 | `backend/main.py` | `POST /admin/login` 设置 cookie；新增 `GET /admin/me`；新增 `POST /admin/logout` | ✅ |
| 1.3 | `src/app/api/admin/[...path]/route.ts` | 转发后端 `Set-Cookie` 头到浏览器 | ✅ |
| 1.4 | `src/app/admin/auth-context.tsx` | 移除 localStorage 逻辑；初始化调 `/admin/me`；`fetchWithAuth` 简化 | ✅ |
| 1.5 | `src/app/admin/page.tsx` + `layout.tsx` + `keys/history` | `token` → `user`；静默 catch 401 | ✅ |

### 认证流程

```
初始化（AuthProvider mount）:
  GET /api/admin/me
  ├── 200 → setUser(response), isLoading = false
  └── 401 → setUser(null), isLoading = false

登录:
  POST /api/admin/login → 后端验证 → Set-Cookie + JSON {user}
  → 前端 setUser(data.user)

登出:
  POST /api/admin/logout → 后端清 Cookie → 前端 setUser(null)

API 请求:
  fetchWithAuth → 普通 fetch（cookie 浏览器自动携带）
  → 收到 401 → logout()
```

---

## Phase 2 — 关键安全修复 [✅ 完成]

### 目标

修复当前代码中可被直接利用的安全漏洞。

### 改动清单

| # | 文件 | 改动内容 | 状态 |
|---|------|----------|------|
| 2.1 | `backend/security.py` | 启动时校验 JWT_SECRET 是否为默认值，是则拒绝启动 | ✅ |
| 2.2 | `backend/main.py` | CORS `allow_origins` 改为环境变量白名单 | ✅ |
| 2.3 | `backend/database.py` | LIKE 查询中转义 `%` 和 `_` | ✅ |
| 2.4 | `backend/main.py` | `GenerateRequest` Pydantic 模型添加枚举/格式/长度校验 | ✅ |
| 2.5 | `backend/seed.py` | 首次运行生成随机密码并打印到控制台 | ✅ |

---

## Phase 3 — 防御纵深 [✅ 完成]

### 目标

构建多层防御体系，提升整体安全性。

### 改动清单

| # | 文件 | 改动内容 | 状态 |
|---|------|----------|------|
| 3.1 | `src/middleware.ts` | **新建** — CSP + 安全 Headers（HSTS/X-Frame-Options/X-Content-Type-Options/Referrer-Policy） | ✅ |
| 3.2 | `backend/middleware.py` | **新建** — 速率限制（slowapi） | ✅ |
| 3.3 | `backend/requirements.txt` | **新建** — 记录 Python 依赖 | ✅ |
| 3.4 | `backend/main.py` | 错误信息截断，过滤数据库路径等敏感信息 | ✅ |
| 3.5 | `src/app/api/admin/[...path]/route.ts` | 请求体大小限制（10MB） | ✅ |

### CSP 策略

```
default-src 'self'
script-src 'self' 'unsafe-inline' (DEV: + 'unsafe-eval')
style-src  'self' 'unsafe-inline'
img-src    'self' data: blob:
font-src   'self'
connect-src 'self'
frame-src  'none'
object-src 'none'
base-uri   'self'
form-action 'self'
```

本应用无外部 CDN/字体/分析脚本，CSP 中不需要任何外部域名。

### 速率限制策略

| 端点 | 限制 |
|------|------|
| `POST /api/generate` | 10/min per IP |
| `POST /api/generate/async` | 20/min per IP |
| `POST /admin/login` | 5/min per IP |
| `GET /admin/dashboard` | 30/min per IP |
| `PUT/POST/DELETE /admin/api-keys` | 10/min per IP |

---

## Phase 4 — 生产加固 [✅ 完成]

### 目标

确保生产环境部署的安全基线。

### 改动清单

| # | 文件 | 改动内容 | 状态 |
|---|------|----------|------|
| 4.1 | `src/app/layout.tsx` | 生产构建时隐藏 `react-dev-inspector`（已有 `NODE_ENV === 'development'` 守卫） | ✅ |
| 4.2 | `.env.example` | **新建** — 环境变量模板 | ✅ |
| 4.3 | `docs/DEPLOYMENT_CHECKLIST.md` | **新建** — 安全基线检查清单 | ✅ |

---

## 验收测试结果

测试套件: `backend/test_security.py` (18 个用例)

```
Phase 1 — Cookie 认证    │ 5/5  PASS
Phase 2 — 安全漏洞修复    │ 7/7  PASS
Phase 3 — 防御纵深       │ 2/2  PASS
Phase 4 — 生产加固       │ 4/4  PASS
-------------------------│----------
总计                      │ 18/18 PASS
```

运行方式:
```bash
cd backend
python -m uvicorn main:app --port 8001
# 新终端:
python backend/test_security.py
```

---

## 执行顺序

每个 Phase 内按编号顺序执行，每步完成后验收，确认无误后进入下一步。

## 相关文件

- `docs/DEPLOYMENT_CHECKLIST.md` — 部署安全基线检查清单
- `backend/test_security.py` — 安全验收测试套件

---

## Round 2 — Reliability & Functional Protection

### 目标

提升系统在生产环境下的健壮性与功能安全，包括请求韧性、资源保护、组件性能与CSRF防御。

### 改动清单

| # | 文件 | 改动内容 | 状态 |
|---|------|----------|------|
| R2.1 | `src/lib/fetch.ts` | `fetchWithRetry`: 失败自动重试3次，指数退避(1s/2s/4s)，仅对5xx/网络错误重试 | -- |
| R2.2 | `src/lib/circuit-breaker.ts` | **新建** — CircuitBreaker: 连续5失败 -> OPEN(30s) -> HALF_OPEN(允许1探测) -> CLOSED | -- |
| R2.3 | `src/server.ts` | 优雅关闭: 监听 SIGTERM/SIGINT, 5秒内排空存量请求后退出 | -- |
| R2.4 | `src/app/page.tsx` | 轮询暂停: `visibilitychange` 监听, 页面隐藏时暂停SSE/轮询, 恢复时续接 | -- |
| R2.5 | `src/components/country-picker.tsx`, `model-picker.tsx`, `image-gallery.tsx` | 组件拆分 + `React.memo`: 细粒度重渲染控制, 减少父组件更新时的不必要渲染 | -- |
| R2.6 | `src/components/image-gallery.tsx` | 图片懒加载: 所有 `<img>` 添加 `loading="lazy" decoding="async"` | -- |
| R2.7 | `backend/main.py` | 过期任务回收: `reap_stale_tasks()` 后台协程, 每60秒清理 stuck >5min 的任务 | -- |
| R2.8 | `src/middleware.ts` | `proxy-image` CORS: 根据 `Origin` 头动态返回 `Access-Control-Allow-Origin`, 支持图片跨域嵌入 | -- |
| R2.9 | `backend/csrf.py`, `backend/main.py` | CSRF: 登录时 cookie 写入 `csrf_token` (JWT jti), 8个写端点验证 `X-CSRF-Token` 头匹配 cookie 值 | -- |

### 关键设计

**CircuitBreaker 状态机:**
- CLOSED: 正常转发。连续失败计数 -> 5 触发 OPEN
- OPEN: 立即拒绝请求。30秒后自动转入 HALF_OPEN
- HALF_OPEN: 放行1个探测请求。成功 -> CLOSED(重置计数); 失败 -> OPEN(重置计时器)

**CSRF Token 传递:**
```
登录成功 -> Set-Cookie: csrf_token=<jti>
前端从 document.cookie 提取 jti -> 设置 X-CSRF-Token 头
后端比较 X-CSRF-Token === cookie 中的 csrf_token
8个受保护端点: POST/PUT/DELETE /admin/*, POST /admin/login, POST /generate/*
```

---

## Round 3 — Architecture & Code Quality

### 目标

消除技术债务，提升代码架构质量、可维护性与部署安全性。

### 改动清单

| # | 文件 | 改动内容 | 状态 |
|---|------|----------|------|
| R3.1 | `src/lib/use-sse.ts`, `backend/sse.py` | **新建/重写** — SSE: 前端 `EventSource` 连接, 后端 `asyncio.Queue` pub/sub 推送, 替代前端轮询 | -- |
| R3.2 | `src/app/admin/page.tsx` 及相关 admin 页面 | 移除 `eslint-disable any`: 所有 `any` 替换为精确 TypeScript 接口类型 | -- |
| R3.3 | `src/lib/proxy.ts` | **新建** — 共享代理函数 `proxyToBackend()`: 统一处理转发、超时、CSRF Token 注入、错误包装 | -- |
| R3.4 | `src/components/ui/modal.tsx` | **新建** — 通用 Modal 组件: overlay 半透明背景、Escape 键关闭、点击 backdrop 关闭、焦点捕获 | -- |
| R3.5 | `.dockerignore` | **新建** — 排除 node_modules/.next/dist/\_\_pycache\_\_/venv/.git/.env 等构建无关文件 | -- |
| R3.6 | `Dockerfile.backend` | 非 root 运行: 添加 `USER appuser`, 减小容器攻击面 | -- |
| R3.7 | `docker-compose.yml` | `healthcheck` 配置 (各服务 30s 间隔/3次重试) + `deploy.resources.limits.memory` (前端512M/后端256M) | -- |
| R3.8 | build 脚本 (`scripts/build.sh`) | 生产压缩: Next.js build 启用压缩 + tsup `minify: true` | -- |
| R3.9 | 全仓库 | `catch(e){}` 静默捕获全部替换为 `logger.error(e)` 记录上下文 | -- |
| R3.10 | `src/lib/logger.ts` | 生产日志门: `console.error` 在 production 下仅输出 `[ERROR]` 前缀, 抑制开发调试信息 | -- |
| R3.11 | `backend/prompts_v2.py` | 常量迁移: `MODEL_STYLE_NAMES` 从 `main.py` 移至 `prompts_v2.py`, 与品类匹配逻辑同处一层 | -- |

### 关键设计

**SSE vs 轮询对比:**

| 维度 | 轮询(旧) | SSE(新) |
|------|----------|---------|
| 实时性 | 3s 间隔(最差3s延迟) | 事件驱动(毫秒级) |
| 服务端开销 | 每次查询DB | 仅推送变更 |
| 网络开销 | 固定3s请求 | 仅变化时推送 |
| 浏览器兼容 | 全兼容 | EventSource API |

**非 root 容器安全性 (Dockerfile.backend):**
```dockerfile
RUN addgroup --system appuser && adduser --system --ingroup appuser appuser
USER appuser
```
确保应用进程以非 root 身份运行，即使被攻陷也无法获得主机 root 权限。
