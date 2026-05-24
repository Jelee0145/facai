# 项目上下文

## 技术栈

- **Framework**: Next.js 16 (App Router), 自定义 HTTP server (`src/server.ts`)
- **Core**: React 19, TypeScript 5 (strict mode)
- **UI**: shadcn/ui (Radix UI), Tailwind CSS 4
- **Backend**: FastAPI (Python, 在 `backend/` 目录), SQLite
- **图片生成**: apimart.ai API (`gpt-image-2` 模型)
- **包管理**: pnpm >=9 (强制)

## 架构要点

- **双服务架构**: Next.js 前端 (port 5000) + FastAPI 后端 (port 8001)
- **API 代理**: `src/app/api/generate/route.ts` 将 `/api/generate/*` 转发到 FastAPI 后端
- **前端也直连后端**: 前端页面 (`page.tsx`) 直接 fetch `http://localhost:8001` 进行异步生成
- **主页面**: "发财计划" — TikTok Shop 九国跨境电商 AI 图片生成工具
- **管理后台**: `/admin` (登录、API Key 管理、生成历史、仪表盘)
- **后端数据库**: SQLite (`backend/data.db`) 存储 API Keys 和生成历史
- **多 Key 负载均衡**: `backend/key_manager.py` 轮询多个 API Key，自动故障转移

## 关键命令

```bash
# 前端开发 (port 5000) — tsx watch + 自定义 server
bash ./scripts/dev.sh

# 前端构建 (Next.js build + tsup 打包 server.ts 到 dist/server.js)
bash ./scripts/build.sh

# 生产启动 (node dist/server.js)
bash ./scripts/start.sh

# 预处理 (安装依赖)
bash ./scripts/prepare.sh

# Lint
pnpm lint

# TypeScript 检查
pnpm ts-check

# 后端开发 (port 8001) — 需要单独启动
cd backend && pip install -r requirements.txt  # 首次
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# 后端测试脚本
cd backend && python test_prompts.py
```

## 开发规范

### 编码
- TypeScript strict 模式; 禁止隐式 `any`、`as any`; catch 子句必须收窄类型
- 清理未使用的变量和导入

### Hydration
- 禁止在 JSX 中直接使用 `typeof window`、`Date.now()`、`Math.random()` — 必须用 `useEffect` + `useState`
- 禁止 `<head>` 标签; 使用 `metadata` 导出或 ReactDOM preload/preconnect/dns-prefetch

### next.config
- 路径必须用 `path.resolve(__dirname, ...)` 或 `process.cwd()` 动态拼接，禁止写死绝对路径

### ESLint
- 禁止 `<head>` 标签 (no-restricted-syntax)
- next.config 中禁止硬编码绝对路径
- `react-hooks/set-state-in-effect` 已关闭

### UI
- 优先使用 `src/components/ui/` 下 shadcn 组件; 导入时用 `@/components/ui/...` 别名
- 主题变量在 `src/app/globals.css` (CSS 变量 + oklch)
- Tailwind CSS v4 (`@import 'tailwindcss'` + `@theme` 语法)

### 包管理
- 仅 pnpm; `npm`/`yarn` 被 `package.json` 的 preinstall 脚本禁止
- registry 已配置为 `https://registry.npmmirror.com` (`.npmrc`)
- `pnpm install` 即可

## 文件 & 目录结构

```
├── backend/                 # FastAPI 后端
│   ├── main.py             # FastAPI app + API 端点
│   ├── prompts_v2.py       # prompt 模板引擎、品类匹配
│   ├── database.py         # SQLite CRUD
│   ├── key_manager.py      # API Key 负载均衡
│   ├── security.py         # JWT 认证
│   └── data.db             # SQLite 数据库 (自动创建)
├── scripts/                # 构建/启动脚本 (bash)
│   ├── build.sh            # pnpm install → next build → tsup 打包 server
│   ├── dev.sh              # 清端口 → tsx watch src/server.ts
│   ├── start.sh            # node dist/server.js
│   └── prepare.sh          # pnpm install
├── src/
│   ├── server.ts           # 自定义 Next.js HTTP server (entrypoint)
│   ├── app/
│   │   ├── page.tsx        # "发财计划" 主页面 (use client)
│   │   ├── layout.tsx      # 根布局 (含 SEO metadata)
│   │   ├── admin/          # 管理后台 (auth-context, history, keys)
│   │   └── api/generate/   # API 代理到 FastAPI 后端
│   └── lib/apimart.ts      # apimart.ai API 客户端 (batchGenerateAndWait 等)
└── .env                    # APIMART_API_KEY (勿提交到公开仓库)
```
