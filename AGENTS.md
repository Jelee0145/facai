# 项目上下文

## 技术栈

- **Framework**: Next.js 16 (App Router), 自定义 HTTP server (`src/server.ts`)
- **Core**: React 19, TypeScript 5 (strict mode)
- **UI**: shadcn/ui (Radix UI), Tailwind CSS 4
- **Backend**: FastAPI (Python, 在 `backend/` 目录), SQLite
- **图片生成**: apimart.ai API (`gpt-image-2` 模型)
- **包管理**: pnpm >=9 (强制)

## 架构要点

- **双服务架构**: Next.js 前端 (port 4524) + FastAPI 后端 (port 8001)
- **API 代理**: `src/app/api/generate/route.ts` 将 `/api/generate/*` 转发到 FastAPI 后端
- **前端也直连后端**: 前端页面 (`page.tsx`) 直接 fetch `http://localhost:8001` 进行异步生成
- **主页面**: "发财计划" — TikTok Shop 九国跨境电商 AI 图片生成工具
- **管理后台**: `/admin` (登录、API Key 管理、生成历史、仪表盘)
- **后端数据库**: SQLite (`backend/data.db`) 存储 API Keys 和生成历史
- **多 Key 负载均衡**: `backend/key_manager.py` 轮询多个 API Key，自动故障转移
- **SSE 实时状态**: Server-Sent Events 实现生成任务状态实时推送
- **CSRF 保护**: CSRF 中间件防御跨站请求伪造
- **Circuit Breaker + Retry**: 前端请求熔断器与自动重试
- **Rate Limiting**: slowapi 实现后端 API 速率限制
- **LLM Provider**: 可切换的 LLM 提供商接入层

## 必读文档

> 在修改代码前，请先阅读 `docs/` 下的相关文档。

| 文档 | 内容 | 何时阅读 |
|------|------|---------|
| [docs/01-系统架构.md](docs/01-系统架构.md) | 双服务架构、请求流转、模块依赖、关键设计决策 | 理解系统全貌、架构变更 |
| [docs/02-数据库设计.md](docs/02-数据库设计.md) | 14 张表 Schema、ER 关系、索引、数据生命周期 | 修改数据库、新增表/字段 |
| [docs/03-后端开发指南.md](docs/03-后端开发指南.md) | 后端模块职责、环境变量、新增端点流程 | 后端开发、新增 API |
| [docs/04-API参考手册.md](docs/04-API参考手册.md) | 全部接口的请求/响应/错误码/SSE 协议 | 修改或新增接口、前端对接 |
| [docs/05-前端开发指南.md](docs/05-前端开发指南.md) | App Router 结构、API 代理、SSE Hook、UI 规范 | 前端开发、组件修改 |
| [docs/06-部署运维.md](docs/06-部署运维.md) | Docker Compose、环境变量、健康检查、备份 | 部署配置、运维操作 |
| [docs/07-安全机制.md](docs/07-安全机制.md) | 双 JWT 流程、CSRF、限流、防暴力破解 | 认证/授权相关改动 |

> **主动维护文档：** 每次完成任务后，必须回顾本次改动是否影响了 `docs/` 中的文档内容，主动更新相关文档以保持同步。新增接口 → 更新 `04-API参考手册.md`；数据库变更 → 更新 `02-数据库设计.md`；架构调整 → 更新 `01-系统架构.md`；新增页面/组件 → 更新 `05-前端开发指南.md`；安全机制改动 → 更新 `07-安全机制.md`。如果新增/删除了文件或引入了新的架构模式，必须同步更新 AGENTS.md 中的文件目录结构或架构要点，确保后续 Agent 能基于本文档正确理解项目。**文档与代码不同步视为任务未完成。**

## 关键命令

```bash
# 前端开发 (port 4524) — tsx watch + 自定义 server
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
│   ├── sse.py              # SSE 实时状态推送
│   ├── csrf.py             # CSRF 保护中间件
│   ├── middleware.py       # 中间件 (CORS, 限流, 请求日志)
│   ├── llm_provider.py     # LLM 提供商抽象层
│   ├── llm_prompts.py      # LLM 提示词模板
│   ├── llm_schema.py       # LLM 输出 schema
│   ├── .env.example        # 环境变量示例
│   └── data.db             # SQLite 数据库 (自动创建)
├── scripts/                # 构建/启动脚本 (bash/PowerShell)
│   ├── build.sh            # pnpm install → next build → tsup 打包 server
│   ├── dev.sh              # 清端口 → tsx watch src/server.ts
│   ├── start.sh            # node dist/server.js
│   ├── prepare.sh          # pnpm install
│   ├── up.ps1              # Docker 一键启动 (PowerShell)
│   └── start-all.sh        # 前后端同时启动脚本
├── src/
│   ├── server.ts           # 自定义 Next.js HTTP server (entrypoint)
│   ├── app/
│   │   ├── page.tsx        # "发财计划" 主页面 (use client)
│   │   ├── layout.tsx      # 根布局 (含 SEO metadata)
│   │   ├── error.tsx       # 全局错误边界
│   │   ├── admin/
│   │   │   ├── page.tsx    # 管理后台首页 (auth-context, history, keys)
│   │   │   ├── error.tsx   # 管理后台错误边界
│   │   │   └── login/
│   │   │       └── page.tsx # 管理后台登录页
│   │   └── api/generate/   # API 代理到 FastAPI 后端
│   ├── lib/
│   │   ├── apimart.ts      # apimart.ai API 客户端 (batchGenerateAndWait 等)
│   │   ├── fetch.ts        # 增强 fetch (超时/重试/CSRF)
│   │   ├── circuit-breaker.ts # 请求熔断器
│   │   ├── proxy.ts        # API 代理转发
│   │   ├── logger.ts       # 前端日志工具
│   │   └── use-sse.ts      # SSE 连接 hook
│   └── components/
│       ├── ui/
│       │   ├── modal.tsx        # 通用模态框
│       │   ├── error-boundary.tsx # 错误边界组件
│       │   ├── toast.tsx        # Toast 提示
│       │   ├── toaster.tsx      # Toast 容器
│       │   └── toast-provider.tsx # Toast 上下文提供者
│       ├── country-picker.tsx   # 国家选择器
│       ├── model-picker.tsx     # 模型选择器
│       └── image-gallery.tsx    # 图片画廊
├── docker-compose.yml      # Docker Compose 编排
├── Dockerfile.backend      # 后端 Dockerfile
├── Dockerfile.frontend     # 前端 Dockerfile
├── .dockerignore           # Docker 构建忽略规则
├── docs/                   # 项目文档
│   ├── 01-系统架构.md      # 系统架构全景 (必读)
│   ├── 02-数据库设计.md    # 数据库 Schema 与 ER 关系 (必读)
│   ├── 03-后端开发指南.md  # 后端开发入门 (必读)
│   ├── 04-API参考手册.md   # 全量 API 接口文档 (必读)
│   ├── 05-前端开发指南.md  # 前端开发入门 (必读)
│   ├── 06-部署运维.md      # Docker 部署与运维 (必读)
│   ├── 07-安全机制.md      # 认证/CSRF/限流设计 (必读)
│   ├── REQUIREMENTS_v2.md  # v2 需求文档
│   ├── TASKS_v2.md         # v2 任务拆分
│   ├── SECURITY_UPGRADE.md # 安全升级变更日志
│   └── DEPLOYMENT_CHECKLIST.md # 部署检查清单
└── .env                    # 环境变量 (勿提交到公开仓库)
```
