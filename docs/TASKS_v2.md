# 优化任务清单 v2

> 对应 REQUIREMENTS_v2.md，按三轮执行
> 完成后参照需求文档验收标准逐项验证

---

## 第一轮：安全基线 & 基础稳定性

### 1.1 随机 Admin 密码
- [x] 修改 `backend/main.py:121` → `secrets.token_urlsafe(12)`
- [x] 修改 `scripts/up.ps1` 的 `Ensure-EnvFiles`：复制 `.env.example` 后自动生成 `ADMIN_PASSWORD`
- [ ] 验证：`grep -r "admin123" backend/ --include="*.py" | grep -v test_` → 空

### 1.2 JWT_SECRET 去掉 fallback
- [x] 修改 `backend/security.py:15` → `os.getenv("JWT_SECRET")`，空则 `sys.exit(1)`
- [ ] 验证：未设 JWT_SECRET → `python -c "import sys; sys.path.insert(0,'backend'); import security"` 应报错退出

### 1.3 生产需 API_AUTH_TOKEN
- [x] 修改 `backend/main.py` → 启动时检查 `NODE_ENV` + `API_AUTH_TOKEN`
- [x] 修改 `backend/.env.example` → 加 `API_AUTH_TOKEN` 注释
- [ ] 验证：`NODE_ENV=production` + 无 API_AUTH_TOKEN → 退出
- [ ] 验证：`NODE_ENV=development` + 无 API_AUTH_TOKEN → 正常启动

### 1.4 seed.py 密码不出日志
- [x] 修改 `backend/seed.py:20-22` → `print("[SEED] Password written to .env")`
- [ ] 验证：运行 seed.py → stdout 无明文密码

### 1.5 全局 Error Boundary
- [ ] 新建 `src/app/error.tsx`（Next.js error boundary）
- [ ] 新建 `src/app/admin/error.tsx`（admin 路由 error boundary）
- [ ] 新建 `src/components/ui/error-boundary.tsx`（React class component）
- [ ] 在 `src/app/layout.tsx` 或 `page.tsx` 中包裹 `ErrorBoundary`
- [ ] 验证：插入 `throw new Error("test")` → 显示降级 UI→ 删除测试代码

### 1.6 alert → Toast
- [ ] 新建 `src/components/ui/toast.tsx`（Toast 组件）
- [ ] 新建 `src/components/ui/toaster.tsx`（Toast 容器）
- [ ] 替换 `src/app/page.tsx` 中全部 11 处 `alert()` → `toast.error()`
- [ ] 验证：`grep "alert(" src/app/page.tsx` → 空
- [ ] 验证：触发错误 → toast 弹出 → 2.5s 消失

### 1.7 CSP unsafe-inline 生产关闭
- [x] 修改 `src/middleware.ts` → 按 `NODE_ENV` 动态拼接 CSP
- [ ] 验证：开发模式 → CSP 含 `unsafe-inline`
- [ ] 验证：生产模式 → CSP 不含 `unsafe-inline` + 页面不报 CSP 违规

---

## 第二轮：可靠性 & 功能防护

### 2.1 fetchWithRetry
- [ ] 新建 `src/lib/fetch.ts` → `fetchWithRetry(url, opts?, retries?)` 
- [ ] 替换 `src/app/page.tsx` 中 3 处 `fetch()` → `fetchWithRetry()`
- [ ] 替换 3 个 Route Handler 中 `fetch(targetUrl)` → `fetchWithRetry()`
- [ ] 验证：后端不可达 → 3 次重试后 502
- [ ] 验证：后端 401 → 不重试

### 2.2 代理熔断器
- [ ] 新建 `src/lib/circuit-breaker.ts` → `CircuitBreaker` 类
- [ ] 3 个 Route Handler 接入熔断器
- [ ] 验证：断后端 → 前 5 次 502 → 第 6 次起立刻 503
- [ ] 验证：恢复后端 → 30s 后自动正常

### 2.3 server.ts 优雅关闭
- [x] 修改 `src/server.ts` → 加 `SIGTERM`/`SIGINT` handler
- [ ] 验证：Ctrl+C → 优雅退出
- [ ] 验证：有进行中请求 → 等完成再退出

### 2.4 轮询后台暂停
- [x] 修改 `src/app/page.tsx:280-340` → 加 `visibilitychange` listener
- [ ] 验证：切 tab → Network 无 status 轮询
- [ ] 验证：切回 → 轮询恢复

### 2.5 组件拆分 + memo
- [ ] 新建 6 个子组件文件（见需求文档 2.5 表）
- [ ] 重构 `src/app/page.tsx` → 引用子组件 + `useMemo`
- [ ] 验证：React DevTools profiler 确认非相关组件不重渲染
- [ ] 验证：功能完全一致

### 2.6 图片懒加载
- [x] 修改 `src/app/page.tsx` + 子组件中所有 `<img>` → 加 `loading="lazy"` `decoding="async"`
- [ ] 验证：Network 面板图片分批加载

### 2.7 后台僵死 task 回收
- [x] 修改 `backend/main.py` → 加 `reap_stale_tasks()` 协程
- [ ] 验证：模拟 6 分钟僵死 task → 60s 内被标记 error

### 2.8 proxy-image CORS 收紧
- [x] 修改 `src/app/api/proxy-image/route.ts:106` → 动态 `Access-Control-Allow-Origin`
- [ ] 验证：同域有 CORS 头，异域无 CORS 头

### 2.9 CSRF 防护
- [ ] 新建 `backend/csrf.py` → `verify_csrf` + token 生成/校验
- [x] 修改 `backend/main.py` → state-changing 端点加 CSRF 依赖
- [x] 修改 `src/app/admin/auth-context.tsx` → 存 `csrfToken` + `fetchWithAuth` 自动注入 `X-CSRF-Token`
- [ ] 验证：无 token → 403
- [ ] 验证：正确 token → 正常
- [ ] 验证：GET 请求不看 CSRF

---

## 第三轮：架构优化 & 代码质量

### 3.1 轮询 → SSE
- [ ] 新建 `backend/sse.py` → `stream_task_progress(task_id)` 生成器
- [ ] `backend/main.py` 新增 `GET /api/generate/status/{task_id}/stream` 端点
- [ ] `backend/main.py` 中 `_run_generation_background` → 进度更新时调用 `push_sse_event()`
- [ ] 新建 `src/lib/use-sse.ts` → `useSSE(url)` hook
- [x] 修改 `src/app/page.tsx` → `setInterval` 替换为 `useSSE()`
- [ ] 验证：生成期间 Network 显示 `eventsource` 类型持续连接
- [ ] 验证：完成后连接自动关闭
- [ ] 验证：切 tab → 继续接收进度
- [ ] 验证：后端重启 → 客户端自动重连

### 3.2 删 eslint-disable any
- [ ] 新建 `src/types.ts` → `ApiKey` / `HistoryItem` / `DashboardStats` / `LLMConfig` interface
- [x] 修改 4 个 admin 页面 → 替换 `any` + 删除 disable 注释
- [ ] 验证：`pnpm ts-check` → 零错误

### 3.3 代理逻辑抽公共函数
- [ ] 新建 `src/lib/proxy.ts` → `proxyToBackend(req, method, path, opts?)`
- [x] 修改 3 个 Route Handler → 一律委托 `proxyToBackend()`
- [ ] 验证：功能回归（generate + async + status + login + me + dashboard）
- [ ] 验证：3 个 Route Handler 文件各 ≤ 40 行

### 3.4 抽取 Modal 组件
- [ ] 新建 `src/components/ui/modal.tsx` → 含 Escape / 遮罩关闭 / aria-modal / focus trap
- [x] 修改 TrendModal + CustomTypeModal → 使用 `<Modal>`
- [ ] 验证：Escape 关闭、遮罩关闭、`aria-modal="true"` 存在

### 3.5 .dockerignore
- [ ] 新建 `.dockerignore`（7 条规则）
- [ ] 验证：`docker build` 的 context < 10MB（无 node_modules）

### 3.6 Docker 后端非 root
- [x] 修改 `Dockerfile.backend` → `USER app`
- [ ] 验证：`docker run --rm backend-test whoami` → `app`

### 3.7 docker-compose healthcheck + limits
- [x] 修改 `docker-compose.yml` → 加 `healthcheck` + `deploy.resources.limits`
- [ ] 验证：`docker compose ps` → 两个服务 `healthy`
- [ ] 验证：kill 后端 → 状态变 `unhealthy`

### 3.8 开启生产压缩
- [x] 修改 `scripts/build.sh` → `--no-minify` 改 `--minify`
- [x] 修改 `Dockerfile.frontend` → 同上
- [ ] 验证：构建后 `dist/server.js` 体积显著减小

### 3.9 静默 catch → error state
- [x] 修改 9 处 `.catch(() => {})` → `.catch((err) => setError(err.message))`
- [ ] 验证：后端挂掉 → admin 各页显示错误提示

### 3.10 console.error 生产屏蔽
- [x] 修改 `src/app/page.tsx` 7 处 → 包 `if (NODE_ENV === "development")`
- [ ] 验证：生产模式 → 触发错误 → Console 无日志

### 3.11 模特风格名数组常量化
- [x] 修改 `backend/prompts_v2.py` → 加 `MODEL_STYLE_NAMES` 常量
- [x] 修改 `backend/main.py` 3 处 → 引用常量
- [ ] 验证：生成结果 `modelStyles` 与修改前一致
