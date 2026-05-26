# 项目优化需求文档 v2

> 三轮迭代：安全 → 可靠性 → 架构与代码质量
> 每项均含改动文件、验收标准、测试方法

---

## 第一轮：安全基线 & 基础稳定性（7 项）

---

### 1.1 随机 Admin 密码

**文件**：`backend/main.py:121`、`scripts/up.ps1`

**当前**
```
admin_pw = os.getenv("ADMIN_PASSWORD", "admin123")
```

**目标**
```python
import secrets
admin_pw = os.getenv("ADMIN_PASSWORD") or secrets.token_urlsafe(12)
```

**验收标准**
- [ ] 不设 `ADMIN_PASSWORD` 环境变量时，`up.ps1` 自动生成随机 12 位密码并写入 `backend/.env`
- [ ] `admin123` 不再作为任何默认密码出现
- [ ] 已有 `backend/.env` 中已设 `ADMIN_PASSWORD` 时不被覆盖

**测试方法**
- 删除 `backend/.env`，运行 `up.ps1`，读 `backend/.env` 确认 `ADMIN_PASSWORD` 为随机字符串且长度 ≥ 12
- `grep -r "admin123" backend/` 无命中（除 test 文件中的测试凭证）

---

### 1.2 JWT_SECRET 去掉 fallback

**文件**：`backend/security.py:15`

**当前**
```python
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-in-production")
```

**目标**
```python
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    print("[SECURITY] CRITICAL: JWT_SECRET 环境变量未设置！")
    sys.exit(1)
```

**验收标准**
- [ ] 环境变量 `JWT_SECRET` 未设置 → 启动直接 `exit(1)`，打印明确提示
- [ ] 代码中不存在 `"change-me-in-production"` 字符串
- [ ] 设置了 `JWT_SECRET` → 正常启动

**测试方法**
- `$env:JWT_SECRET=""` → `python -c "import security"` → 确认 `exit(1)` + 有错误信息
- `$env:JWT_SECRET="test-secret"` → `python -c "import security; print('OK')"` → 输出 OK

---

### 1.3 生产需 API_AUTH_TOKEN

**文件**：`backend/main.py:85-93`、`backend/.env.example`

**目标**
- 启动时检查：若 `NODE_ENV` 环境变量为 `"production"` 且 `API_AUTH_TOKEN` 为空 → `sys.exit(1)`
- 开发环境（`NODE_ENV != "production"`）→ 保持现有逻辑，允许空 token
- `backend/.env.example` 添加 `# API_AUTH_TOKEN — 生产环境必填` 注释

**验收标准**
- [ ] 生产模式 + `API_AUTH_TOKEN` 为空 → 启动失败
- [ ] 开发模式 + `API_AUTH_TOKEN` 为空 → 正常启动，`/api/generate` 无 auth 校验
- [ ] `.env.example` 含 `API_AUTH_TOKEN` 变量及注释

**测试方法**
- `$env:NODE_ENV="production"; $env:API_AUTH_TOKEN=""` → 启动后端，确认退出
- `$env:NODE_ENV="development"; $env:API_AUTH_TOKEN=""` → 启动后端，`POST /api/generate` 返回 422（Pydantic）而非 403

---

### 1.4 seed.py 密码不出日志

**文件**：`backend/seed.py:20-22`

**当前**
```python
print(f"[SEED] 密码: {seed_password}")
```

**目标**
```python
print("[SEED] Admin password has been written to backend/.env")
# 密码只写入文件，不打印到 stdout
```

**验收标准**
- [ ] stdout 中不再出现任何明文密码
- [ ] `.env` 文件中密码依然正确写入

**测试方法**
- 运行 `python backend/seed.py 2>&1` → 输出不含密码
- 读 `backend/.env` → `ADMIN_PASSWORD` 有值

---

### 1.5 全局 Error Boundary

**文件**：新建 `src/app/error.tsx`、新建 `src/app/admin/error.tsx`、新建 `src/components/ui/error-boundary.tsx`

**目标**
- `src/app/error.tsx`：Next.js 文件约定，路由级崩溃显示"页面出了点问题" + 重试按钮
- `src/app/admin/error.tsx`：同上，admin 子路由
- `src/components/ui/error-boundary.tsx`：React class component ErrorBoundary，包裹 `page.tsx` 主内容区
- 捕获错误后展示降级 UI，不白屏

**验收标准**
- [ ] `page.tsx` 中任意子组件 `throw new Error("test")` → 页面显示错误提示而不是白屏
- [ ] 点击"重试"恢复
- [ ] admin 页面崩溃 → 显示 admin 错误页面

**测试方法**
- 在 `page.tsx` 渲染中插入 `throw new Error("test boundary")`，刷新 → 看到降级 UI 而非白屏
- 删除测试代码后页面恢复正常
- admin 路由同样验证

---

### 1.6 alert → Toast

**文件**：新建 `src/components/ui/toast.tsx`、新建 `src/components/ui/toaster.tsx`、`src/app/page.tsx`

**目标**
- `toast.tsx`：`toast.success(msg)` / `toast.error(msg)` / `toast.warning(msg)`
- 底部居中弹出，2.5 秒自动消失，支持堆叠
- 替换 `page.tsx` 中全部 11 处 `alert()`
- `toaster.tsx`：渲染 toast 容器的 provider 组件，挂载到 `<body>`

**验收标准**
- [ ] 生成失败 → 页面底部出现 error toast（红色），2.5 秒自动消失
- [ ] 连续触发 3 个 toast → 堆叠显示，不互相覆盖
- [ ] `page.tsx` 中零 `alert()` 调用
- [ ] toast 点击可立即关闭

**测试方法**
- 触发一次测试生成（选择无效图片 URL）→ 观察 toast 出现并自动消失
- 快速点击 3 次生成 → 3 个 toast 依次堆叠
- `grep -r "alert(" src/app/page.tsx` → 无结果

---

### 1.7 CSP unsafe-inline 生产关闭

**文件**：`src/middleware.ts`

**当前**
```typescript
let csp = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; ..."
```

**目标**
```typescript
const isProd = process.env.NODE_ENV === "production";
const scriptSrc = isProd ? "'self'" : "'self' 'unsafe-inline'";
const styleSrc = isProd ? "'self'" : "'self' 'unsafe-inline'";
let csp = `default-src 'self'; script-src ${scriptSrc}; style-src ${styleSrc}; ...`
```

**验收标准**
- [ ] 开发环境：CSP header 含 `'unsafe-inline'`
- [ ] 生产环境：CSP header 不含 `'unsafe-inline'`
- [ ] Tailwind / Next.js 在生产模式下页面渲染不报 CSP 违规

**测试方法**
- `pnpm tsx watch src/server.ts` → 浏览器 DevTools → Network → 响应头 `Content-Security-Policy` 含 `unsafe-inline`
- `NODE_ENV=production pnpm tsx watch src/server.ts` → 同上，不含 `unsafe-inline`，页面功能正常无 CSP 报错（Console 无 `[Report Only]` 消息）

---

## 第二轮：可靠性 & 功能防护（9 项）

---

### 2.1 fetchWithRetry

**文件**：新建 `src/lib/fetch.ts`；修改 `src/app/page.tsx`、3 个 Route Handler

**目标**
```typescript
// src/lib/fetch.ts
export async function fetchWithRetry(url: string, options?: RequestInit, maxRetries = 3): Promise<Response>
```
- 首次失败等待 1s 重试、第二次 2s、第三次 4s
- 只重试网络错误和 502/503/504，不重试 4xx
- 全部失败后抛出最后一次的错误
- 替换 `page.tsx` 中 `handleGenerate` / `handleQuickTest` / `handleSingleImageTest` 的裸 `fetch()`
- 3 个 Route Handler 的 `fetch(targetUrl)` 替换为 `fetchWithRetry`

**验收标准**
- [ ] 后端临时不可达 → 自动重试 3 次后返回 502
- [ ] 后端返回 401 → 不重试，直接返回
- [ ] 正常请求走一次成功不触发重试

**测试方法**
- 断掉后端（kill python 进程），触发前端生成 → 等待 ~7s（1+2+4），收到 3 次重试后 502
- 后端正常运行 → 生成请求一次成功，控制台无重试日志
- 登录用错误密码 → 返回 401，无重试

---

### 2.2 代理熔断器

**文件**：新建 `src/lib/circuit-breaker.ts`；3 个 Route Handler

**目标**
```typescript
// src/lib/circuit-breaker.ts
export class CircuitBreaker {
  private failures = 0;
  private lastFailureTime = 0;
  private threshold = 5;
  private timeout = 30000; // 30s
  async call(fn: () => Promise<Response>): Promise<Response>
}
```
- 连续 5 次后端调用失败 → 进入 OPEN 状态
- OPEN 期间直接返回 503，不请求后端
- 30 秒后进入 HALF_OPEN，放行一次探测
- 探测成功 → 重置为 CLOSED

**验收标准**
- [ ] 后端挂掉 → 前 5 次请求返回 502（重试后），第 6 次起立即返回 503（熔断）
- [ ] 后端恢复 → 30 秒后请求自动探测成功，恢复正常
- [ ] 熔断期间不产生后端网络请求

**测试方法**
- kill 后端 → 连续请求 6 次 → 前 5 次慢返回，第 6 次立刻返回 503
- 重启后端 → 等待 30 秒 → 下一次请求恢复正常
- 日志确认 OPEN 期间无 `fetch` 调用

---

### 2.3 server.ts 优雅关闭

**文件**：`src/server.ts`

**目标**
```typescript
const server = app.listen(port, () => { ... });

let shuttingDown = false;
process.on("SIGTERM", () => gracefulShutdown(server, "SIGTERM"));
process.on("SIGINT", () => gracefulShutdown(server, "SIGINT"));

function gracefulShutdown(server: http.Server, signal: string) {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log(`[SHUTDOWN] Received ${signal}, shutting down...`);
  server.close(() => { console.log("[SHUTDOWN] Server closed"); process.exit(0); });
  setTimeout(() => { console.log("[SHUTDOWN] Force exit"); process.exit(1); }, 5000);
}
```

**验收标准**
- [ ] `Ctrl+C` → 服务器优雅退出，在 5 秒内关闭
- [ ] 有正在处理的请求时，等待请求完成后再退出
- [ ] 超 5 秒强制退出

**测试方法**
- 启动前端 → 发起一个长请求 → 按 Ctrl+C → 确认服务等到请求完成才退出（不超 5s）
- 无请求时 Ctrl+C → 立即退出

---

### 2.4 轮询后台暂停 + SSE 替代（见 3.4）

> 注：本轮先做 visibility 暂停。SSE 替代在第三轮

**文件**：`src/app/page.tsx:280-340`

**目标**
- 加 `document.addEventListener("visibilitychange", ...)` handler
- 页面隐藏时 `clearInterval(pollingRef.current)`，恢复时重新 `setInterval`

**验收标准**
- [ ] 切换到别的 tab → Network 面板不再有 `/api/generate/status/` 请求
- [ ] 切回 tab → 轮询恢复
- [ ] 轮询停止/恢复不影响任务结果（任务在后台继续执行）

**测试方法**
- 触发一次全量生成 → 打开 DevTools Network → 切到别的 tab → 停止出现新请求 → 切回 → 恢复请求
- 在后台 tab 期间任务完成后切回 → 页面正确展示结果

---

### 2.5 组件拆分 + memo

**文件**：新建 6 个子组件文件；修改 `src/app/page.tsx`

**拆分目标**
| 组件 | 文件 | 内容 | memo 理由 |
|------|------|------|----------|
| `CountryPicker` | `src/components/country-picker.tsx` | 国家选择网格（L597-611） | country 不变时不渲染 |
| `ModelPicker` | `src/components/model-picker.tsx` | 模型选择网格（L620-636） | model 不变时不渲染 |
| `ProductTypePicker` | `src/components/product-type-picker.tsx` | 品类选择 + 搜索（L700-780） | productType 不变时不渲染 |
| `ImageGallery` | `src/components/image-gallery.tsx` | 结果图展示网格（L886-940） | images 不变时不渲染 |
| `TrendModal` | `src/components/trend-modal.tsx` | 趋势复刻弹窗（L1117-1184） | 不打开时不渲染 |
| `CustomTypeModal` | `src/components/custom-type-modal.tsx` | 自定义品类弹窗（L1073-1115） | 不打开时不渲染 |
- 全部 `export default React.memo(...)` 
- `categories` 和 `filteredProducts` 计算用 `useMemo`

**验收标准**
- [ ] 切换模型时 CountryPicker 不重渲染（React DevTools profiler 确认）
- [ ] 功能与拆分前完全一致
- [ ] TypeScript 编译无错误

**测试方法**
- 安装 React DevTools Profiler → 录制一次生成操作 → 查看火焰图，确认非相关组件未重渲染
- 功能回归：选择国家/模型/品类/上传图片/测试生成/全量生成/趋势弹窗/自定义品类 CRUD → 全部正常

---

### 2.6 图片懒加载

**文件**：`src/app/page.tsx`（所有 `<img>`）

**目标**
- 所有 `<img>` 加 `loading="lazy"` + `decoding="async"`
- 折叠区域（如趋势弹窗、自定义品类弹窗）内的图受益最大

**验收标准**
- [ ] 每个 `<img>` 均有 `loading="lazy"` 属性
- [ ] DevTools → Network → 图片分批加载，不一次性加载全部

**测试方法**
- `grep -c 'loading="lazy"' src/app/page.tsx src/components/image-gallery.tsx` → 与 `<img` 标签数一致
- 打开页面 → DevTools Network → 滚动到结果区域前不加载图片

---

### 2.7 后台僵死 task 回收

**文件**：`backend/main.py`

**目标**
- `@app.on_event("startup")` 中创建 `asyncio.create_task(reap_stale_tasks())`
- `reap_stale_tasks()` 每 60 秒扫描 `task_store`
- 状态 `"generating"` 且 `start_time` 超过 300 秒 → 标记 `"error"` + error_msg `"Task timed out"`

**验收标准**
- [ ] 模拟一个僵死在 "generating" 状态 6 分钟的 task → 等待回收周期 → 状态变为 "error"
- [ ] 正常的短期 generating task 不被误杀

**测试方法**
- Python TestClient 创建 task，手动改 `task_store[task_id]["start_time"] = time.time() - 400` → 等待 60s → `GET /api/generate/status/{task_id}` 返回 status="error"
- 正在生成中的 task（< 5min）→ 状态不变

---

### 2.8 proxy-image CORS 收紧

**文件**：`src/app/api/proxy-image/route.ts:106`

**当前**
```
Access-Control-Allow-Origin: *
```

**目标**
- 只当请求 `Origin` 头匹配 `BACKEND_URL` 或本域（`localhost:5000` 或自定义域名）时返回该 origin
- 否则不返回 `Access-Control-Allow-Origin`（浏览器拒绝跨域）

**验收标准**
- [ ] 同域请求 → 图片正常加载
- [ ] 不同域请求 → 浏览器 CORS 报错，图片不加载
- [ ] `curl -H "Origin: https://evil.com"` → 响应中无 `Access-Control-Allow-Origin`

**测试方法**
```bash
# 同域：有 CORS 头
curl -sI "http://localhost:5000/api/proxy-image?url=..." -H "Origin: http://localhost:5000" | grep Access-Control
# 异域：无 CORS 头
curl -sI "http://localhost:5000/api/proxy-image?url=..." -H "Origin: https://evil.com" | grep Access-Control
```

---

### 2.9 CSRF 防护

**文件**：新建 `backend/csrf.py`、修改 `backend/main.py`、修改 `src/app/admin/auth-context.tsx`

**目标**
- 登录成功时，后端返回 `csrf_token`（随机 32 位 hex）在 JSON body 中
- `auth-context.tsx` 将 `csrfToken` 存入 state，`fetchWithAuth` 自动注入 `X-CSRF-Token` header
- 后端新建 `csrf.py`：`def verify_csrf(request: Request) -> bool`
  - 从 `X-CSRF-Token` header 取值，与登录时返回的 token 比对
  - 比对失败 → `HTTPException(403, "CSRF token invalid")`
- 以下端点加 `_csrf=Depends(verify_csrf)` 依赖：
  - `POST /admin/api-keys` / `DELETE /admin/api-keys/{id}`
  - `POST /admin/llm-config` / `POST /admin/llm-config/test`
  - `POST /api/custom-types` / `DELETE /api/custom-types/{id}`
  - `POST /admin/logout`

**验收标准**
- [ ] 不带 `X-CSRF-Token` header 的 state-changing 请求 → 403
- [ ] 带正确 token → 正常执行
- [ ] 带错误 token → 403
- [ ] GET 请求不校验 CSRF

**测试方法**
- 登录获取 `csrf_token` → 用不带 token 的 curl POST `/admin/api-keys` → 403
- 带正确 token → 200
- `GET /admin/dashboard` → 无需 token，正常返回

---

## 第三轮：架构优化 & 代码质量（11 项）

---

### 3.1 轮询 → SSE（最大改动）

**文件**：新增 `backend/sse.py`、修改 `backend/main.py`、修改 `src/app/page.tsx`、新建 `src/lib/use-sse.ts` hook

**后端**
- 新增 `@app.get("/api/generate/status/{task_id}/stream")` SSE 端点
  - Content-Type: `text/event-stream`
  - 每有进度变化推送：
    ```
    data: {"completed": 5, "total": 14, "status": "generating", "images": [{"index": 0, "url": "..."}]}
    ```
  - 任务完成：
    ```
    data: {"status": "completed", "result": {...}}
    ```
  - 任务失败：
    ```
    data: {"status": "failed", "error": "..."}
    ```
  - 5 分钟无进展 → 关闭连接
  - 客户端断开 → `asyncio.CancelledError` 捕获后清理

**前端**
- 新建 `src/lib/use-sse.ts`：
  ```typescript
  export function useSSE(url: string) {
    // 用 EventSource 订阅，返回 { data, error, isConnected }
  }
  ```
- `page.tsx` 中 `handleGenerate` → `startPolling` 改为 `subscribeSSE`
- 收到 `completed` 或 `failed` → 自动关闭 EventSource
- 此改动删除 `setInterval` 轮询逻辑 + 2.4 的 visibility 暂停逻辑（不再需要）

**验收标准**
- [ ] 生成开始后，前端实时收到进度更新（不需要轮询）
- [ ] 生成完成后 EventSource 自动关闭
- [ ] 切换到其他 tab → SSE 连接不被浏览器暂停（server-sent events 天然不挂起）
- [ ] 任务失败 → 前端收到失败事件并展示错误
- [ ] 后端重启 → 客户端 EventSource 自动重连

**测试方法**
- 触发全量生成 → DevTools Network → 看到 `stream` 请求 type 为 `eventsource`，持续接收数据帧
- 切 tab → 回来 → 进度继续更新（不依赖 visibilitychange）
- 主动 kill 后端 → 前端收到 error 事件 → 5 秒后自动重连
- 生成完成后 EventSource 关闭，Network 面板不再有活跃连接

---

### 3.2 删 eslint-disable any

**文件**：4 个 admin 页面

**目标**
- 定义以下 interface（放在 `src/types.ts` 或各页面顶部）：
  ```typescript
  interface ApiKey { id: number; key_value: string; created_at: string; last_used_at?: string; usage_count: number; is_active: boolean }
  interface HistoryItem { id: number; task_id: string; product_type: string; country: string; model: string; status: string; created_at: string; total_images: number; success_count: number; elapsed_seconds: number }
  interface DashboardStats { total_generations: number; success_rate: number; total_images: number; active_keys: number; ... }
  interface LLMConfig { llm_api_key?: string; llm_model?: string; llm_base_url?: string }
  ```
- 删除文件头的 `/* eslint-disable @typescript-eslint/no-explicit-any */`
- 修正所有 `any` 类型为正确 interface

**验收标准**
- [ ] `grep -r "eslint-disable.*no-explicit-any" src/app/admin/` → 无匹配
- [ ] `pnpm ts-check` → 零错误
- [ ] `pnpm lint` → 零错误

**测试方法**
- 运行 `pnpm ts-check` → 全部通过
- `pnpm lint` → 无新增 warning

---

### 3.3 代理逻辑抽公共函数

**文件**：新建 `src/lib/proxy.ts`；修改 3 个 Route Handler

**目标**
```typescript
// src/lib/proxy.ts
export async function proxyToBackend(
  req: NextRequest,
  method: string,
  backendPath: string,  // e.g. "/admin/login" or "/api/generate"
  options?: { maxBodySize?: number; injectHeaders?: Record<string, string> }
): Promise<NextResponse>
```
- 3 个 Route Handler 中去重为调用 `proxyToBackend(req, method, path, opts)`
- 删除重复的 header 过滤、body 限制、URL 拼接、错误处理逻辑

**验收标准**
- [ ] 功能回归：`/api/generate`、`/api/generate/async`、`/api/admin/login`、`/api/admin/me` 全部正常
- [ ] 3 个 Route Handler 文件行数各 ≤ 40 行（代理逻辑从各 ~70 行缩减）

**测试方法**
- 功能回归测试套件（登录/登出/获取用户/测试生成/异步生成/状态查询）→ 全部通过
- `wc -l src/app/api/generate/route.ts src/app/api/generate/[...path]/route.ts src/app/api/admin/[...path]/route.ts` → 比原来显著缩短

---

### 3.4 抽取 `<Modal>` 组件

**文件**：新建 `src/components/ui/modal.tsx`；修改 `src/app/page.tsx`、`src/components/trend-modal.tsx`、`src/components/custom-type-modal.tsx`

**目标**
```tsx
// src/components/ui/modal.tsx
interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}
export function Modal({ isOpen, onClose, title, children }: ModalProps) { ... }
```
- 统一处理：overlay + backdrop blur + 点击遮罩关闭 + Escape 关闭 + `aria-modal`
- 各 Modal 仅提供 `title` + `children` 内容

**验收标准**
- [ ] 趋势弹窗和自定义品类弹窗通用同一个 `<Modal>` 组件
- [ ] Escape 键关闭两个弹窗
- [ ] 点击遮罩层关闭两个弹窗
- [ ] `aria-modal="true"` 出现在弹窗 DOM 上

**测试方法**
- 打开趋势弹窗 → 按 Escape → 弹窗关闭
- 打开自定义品类弹窗 → 点遮罩 → 弹窗关闭
- DevTools → 查看元素 → `[aria-modal="true"]` 存在

---

### 3.5 .dockerignore

**文件**：新建 `D:\project\projects\.dockerignore`

**目标**
```
node_modules
.next
.git
dist
**/data.db
**/__pycache__
.env
.env.*
!.env.example
*.log
```

**验收标准**
- [ ] `docker build` 的 context 不包含 `node_modules`（体积显著减小）
- [ ] `.git` 和 `data.db` 不进入镜像
- [ ] `.env.example` 保留在镜像中

**测试方法**
- `docker build -t test-build .` → 查看构建日志，上下文大小 ≤ 10MB（不含 node_modules）
- 运行容器，确认 `.env.example` 存在、`.git` 不存在

---

### 3.6 Docker 后端非 root

**文件**：`Dockerfile.backend`

**目标**
```dockerfile
RUN addgroup --system app && adduser --system --ingroup app app
USER app
```

**验收标准**
- [ ] 容器内 `whoami` → `app`，不是 `root`
- [ ] Python 进程以 `app` 用户运
- [ ] `/health` 端点正常响应

**测试方法**
- `docker build -t backend-test -f Dockerfile.backend .`
- `docker run --rm backend-test whoami` → 输出 `app`
- `docker run --rm -p 8001:8001 backend-test` → `curl localhost:8001/health` → 200

---

### 3.7 docker-compose healthcheck + limits

**文件**：`docker-compose.yml`

**目标**
```yaml
services:
  backend:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: '512M'
  frontend:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 30s
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: '512M'
```

**验收标准**
- [ ] `docker compose up -d` → `docker compose ps` 显示两个服务均为 `healthy`
- [ ] 后端健康检查失败 3 次 → 服务标记为 `unhealthy`
- [ ] 前端在 backend healthy 之后才标记 healthy（`depends_on` 条件）

**测试方法**
- `docker compose up -d` → 等待 30s → `docker compose ps` → STATUS 列显示 `healthy`
- 手动 kill 后端进程 → `docker compose ps` → backend 变 `unhealthy`

---

### 3.8 开启生产压缩

**文件**：`scripts/build.sh`、`Dockerfile.frontend`

**当前**
```
pnpm exec tsup src/server.ts --format cjs --no-minify ...
```

**目标**
```
pnpm exec tsup src/server.ts --format cjs --minify ...
```

**验收标准**
- [ ] `dist/server.js` 经压缩体积明显小于未压缩版本
- [ ] 功能无退化

**测试方法**
- 运行 `bash scripts/build.sh` → 比较 `dist/server.js` 体积与之前
- 启动 `node dist/server.js` → `curl localhost:5000` → 200

---

### 3.9 静默 catch → error state

**文件**：4 处 `.catch(() => {})` 位置

**目标**
- 每个 `.catch` 后至少设置一个 `useState` error 标志，并用 `logger.error` 记录错误
- UI 上展示错误信息："加载失败，请刷新重试"

**验收标准**
- [ ] 后端不可达时，全部 admin 页面显示错误提示而不是空白
- [ ] `.catch(() => {})` 在 admin 页面中减为 0

**测试方法**
- kill 后端 → 打开 admin 各页面 → 每页都显示"加载失败"相关提示
- `grep -r "catch(() =>" src/app/admin/` → 0 匹配（auth-context logout 除外）

---

### 3.10 console.error 生产屏蔽

**文件**：新建 `src/lib/logger.ts`；替换全项目 `console.error` 为 `logger.error`

**目标**
```typescript
// src/lib/logger.ts
const IS_PRODUCTION = typeof process !== "undefined" && process.env?.NODE_ENV === "production";
export const logger = {
  error: (...args: unknown[]) => { if (!IS_PRODUCTION) console.error(...args); },
  warn:  (...args: unknown[]) => { if (!IS_PRODUCTION) console.warn(...args); },
  log:   (...args: unknown[]) => { if (!IS_PRODUCTION) console.log(...args); },
};
```

**验收标准**
- [ ] 开发模式 → 控制台可见错误日志
- [ ] 生产模式 → 控制台无错误日志

**测试方法**
- `NODE_ENV=development pnpm tsx watch src/server.ts` → 触发错误 → Console 有 log
- `NODE_ENV=production pnpm tsx watch src/server.ts` → 同上 → Console 无 log

---

### 3.11 模特风格名数组常量化

**文件**：`backend/main.py`、`backend/prompts_v2.py`

**目标**
- `prompts_v2.py` 顶部新增：
  ```python
  MODEL_STYLE_NAMES = [
      "时尚街拍风", "都市休闲风", "杂志大片风", "生活方式风",
      "自信站姿风", "活力户外风", "职业商务风", "海滩度假风",
      "艺术优雅风", "运动活力风", "奢华时尚风",
  ]
  ```
- `main.py` 中 3 处硬编码替换为 `MODEL_STYLE_NAMES[idx]`

**验收标准**
- [ ] `grep "时尚街拍风" backend/main.py` → 0 匹配（只有 import）
- [ ] 生成结果中模特风格名与之前一致

**测试方法**
- 调用 `/api/generate` test 模式 → 返回的 `modelStyles` 与之前一致
- `grep -r "时尚街拍风" backend/main.py` → 无匹配

---

## 验收总表

| 轮次 | 项数 | 总验收点 | 终点指令 |
|------|------|----------|---------|
| 第一轮 | 7 | 18 点 | 手动启动 up.ps1 → 前端可用 → 触发一次完整生成流程 |
| 第二轮 | 9 | 24 点 | 断后端 + 恢复 → 熔断生效 + 前端自愈，CSRF 403 测试通过 |
| 第三轮 | 11 | 28 点 | SSE 实时进度不卡顿、TS 零错误、docker compose 健康检查通过 |

---

## 附录：测试脚本

### A. 安全基线检查脚本
```bash
# 1. 检查默认密码
grep -r "admin123" backend/ --include="*.py" | grep -v test_

# 2. 检查 JWT fallback
grep "change-me-in-production" backend/security.py

# 3. 检查 seed 日志
python -c "from backend.seed import *; " 2>&1 | grep -i password | grep -v ".env"

# 4. 检查 CSP — 生产模式
curl -sI http://localhost:5000 | grep "Content-Security-Policy"
```

### B. 可靠性检查脚本
```bash
# 熔断测试
for i in $(seq 1 7); do
  echo "=== Request $i ==="
  curl -s -w "\nHTTP %{http_code}\n" http://localhost:5000/api/admin/dashboard
done

# CSRF 测试
TOKEN=$(curl -s -X POST http://localhost:8001/admin/login -H "Content-Type: application/json" -d '{"username":"admin","password":"xxx"}' | jq -r '.csrf_token')
# 不带 CSRF → 应 403
curl -s -X POST http://localhost:8001/admin/api-keys -H "Content-Type: application/json" -d '{"key_value":"test"}' -w "\n%{http_code}\n"
# 带 CSRF → 应正常
curl -s -X POST http://localhost:8001/admin/api-keys -H "Content-Type: application/json" -H "X-CSRF-Token: $TOKEN" -d '{"key_value":"test"}'
```

### C. SSE 测试脚本
```bash
# 触发异步生成后订阅 SSE
curl -N http://localhost:8001/api/generate/status/{task_id}/stream
# 预期连续输出 data: {...} 帧直到 completed
```
