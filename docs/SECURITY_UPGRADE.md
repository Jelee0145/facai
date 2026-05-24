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
