# 发财计划 — AI 商品图生成平台

面向 TikTok Shop / 抖音电商的一站式 AI 商品图生成 SaaS 平台。上传商品图，一键生成 9 张主图 + 2 张辅助图，附带爆款标题和热门标签，覆盖美国、英国及东南亚 9 国市场。

## 功能亮点

- **一键生成** — 上传商品图，自动匹配品类、选择 AI 风格，批量生成 11 张电商主图
- **9 国市场** — 支持美国、英国、印尼、泰国、越南、菲律宾、马来西亚、新加坡、墨西哥
- **6 种 AI 风格** — 通用、人像、时尚、产品、艺术、爆款，按品类智能匹配最佳风格
- **LLM 智能分析** — 集成阿里云 DashScope（Qwen3-VL），智能配置提示词和场景，不可用时自动降级为模板
- **积分计费系统** — 用户注册、积分充值、套餐管理、消费明细、失败自动退款
- **管理后台** — 数据看板、API Key 池管理（自动故障转移）、用户管理、LLM 配置、扣费控制
- **实时进度** — SSE 推送生成进度，支持异步生成和超时任务自动回收
- **安全认证** — JWT + CSRF 双重防护、bcrypt 密码加密、登录锁定、Token 撤销

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS v4 + shadcn/ui |
| 后端 | Python FastAPI + Uvicorn + Pydantic v2 |
| 数据库 | SQLite（14 张表，自动迁移） |
| AI 服务 | apimart.ai（图片生成）+ 阿里云 DashScope / Qwen3-VL（提示词分析） |
| 部署 | Docker Compose（前端 Node 22 + 后端 Python 3.11） |
| 包管理 | pnpm 9+（前端）、pip（后端） |

## 项目结构

```
├── src/app/                    # 前端页面
│   ├── page.tsx                # 主工作台（图片生成）
│   ├── admin/                  # 管理后台
│   │   ├── login/page.tsx      #   登录
│   │   ├── users/page.tsx      #   用户管理
│   │   ├── billing/page.tsx    #   计费管理
│   │   ├── keys/page.tsx       #   API Key 管理
│   │   ├── llm/page.tsx        #   LLM 配置
│   │   └── history/page.tsx    #   生成历史
│   └── api/                    # Next.js API 代理层
├── src/components/ui/          # shadcn/ui 组件
├── src/lib/                    # 工具库（代理、SSE、fetch、日志等）
├── backend/
│   ├── main.py                 # FastAPI 主入口 + 全部路由
│   ├── database.py             # SQLite 数据层（14 张表 + 自动迁移）
│   ├── security.py             # JWT 认证、CSRF、密码加密、登录锁定
│   ├── llm_provider.py         # DashScope LLM 集成
│   ├── prompts_v2.py           # 品类匹配、风格选择、提示词构建
│   ├── key_manager.py          # API Key 池管理与故障转移
│   └── requirements.txt
├── docker-compose.yml          # Docker 一键部署
├── Dockerfile.backend
├── Dockerfile.frontend
└── scripts/                    # 启动脚本
```

## 快速开始

### 环境要求

- Node.js 22+
- Python 3.11+
- pnpm 9+

### 本地开发

**1. 克隆项目**

```bash
git clone <repo-url> && cd projects
```

**2. 后端**

```bash
cd backend
cp .env.example .env          # 编辑 .env 配置各项参数
pip install -r requirements.txt
python main.py                 # 启动在 http://localhost:8001
```

**3. 前端**

```bash
cd ..                          # 回到项目根目录
pnpm install
pnpm dev                       # 启动在 http://localhost:4524
```

或使用启动脚本：

```bash
bash scripts/dev.sh
```

### Docker Compose 部署

```bash
cp backend/.env.example backend/.env   # 编辑配置
docker compose up -d --build
```

- 前端：http://localhost:4524
- 后端：http://localhost:8001

## 环境变量

在 `backend/.env` 中配置（从 `backend/.env.example` 复制）：

| 变量 | 必填 | 说明 |
|------|------|------|
| `JWT_SECRET` | 否 | JWT 签名密钥，留空则自动生成 |
| `API_AUTH_TOKEN` | 否 | 前后端内部通信令牌 |
| `CORS_ORIGINS` | 否 | 允许的跨域来源（默认 `http://localhost:4524`） |
| `ADMIN_PASSWORD` | 否 | 管理员密码，留空则自动生成随机密码 |
| `NODE_ENV` | 否 | `development` / `production` |
| `COOKIE_SECURE` | 否 | Cookie 是否仅 HTTPS（生产设为 `true`） |

## 管理后台

访问 `/admin/login`，使用管理员账号登录。后台功能：

- **数据看板** — 用户数、生成量、收入统计
- **用户管理** — 创建/冻结/删除用户、编辑备注
- **计费管理** — 积分套餐配置、订单审核入账、扣费点数调整
- **API Key 管理** — 多 Key 轮换、故障自动转移
- **LLM 配置** — DashScope 模型切换、提示词测试
- **生成历史** — 全部用户的生成记录查询

## API 概览

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 用户注册 |
| POST | `/auth/login` | 用户登录 |
| POST | `/auth/logout` | 退出登录 |
| GET | `/auth/me` | 当前用户信息 |

### 图片生成

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/generate` | 同步生成（单图测试/对比/详情模式） |
| POST | `/api/generate/async` | 异步生成（完整 11 张） |
| GET | `/api/generate/status/{task_id}` | 查询任务状态 |
| GET | `/api/generate/stream/{task_id}` | SSE 实时进度推送 |

### 用户

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/user/wallet` | 钱包余额 |
| GET | `/user/packages` | 积分套餐列表 |
| GET | `/user/history` | 生成历史 |
| GET | `/user/history/{id}` | 历史详情 |
| GET/POST | `/user/orders` | 订单列表/创建 |

### 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/admin/dashboard` | 数据看板 |
| CRUD | `/admin/users` | 用户管理 |
| CRUD | `/admin/api-keys` | API Key 管理 |
| CRUD | `/admin/credit-packages` | 积分套餐 |
| PUT | `/admin/llm-config` | LLM 配置 |
| PUT | `/admin/generation-cost` | 扣费点数 |
| PUT | `/admin/change-password` | 修改管理员密码 |

## 开发规范

- **包管理** — 必须使用 pnpm，项目已配置 `preinstall` 脚本拦截 npm/yarn
- **组件** — 优先使用 `src/components/ui/` 中的 shadcn/ui 组件
- **类型** — 使用 TypeScript，利用 `@/` 路径别名导入模块
- **样式** — Tailwind CSS v4，主题变量定义在 `globals.css`
- **后端** — FastAPI + Pydantic v2，新增接口需添加请求模型和速率限制

## 参考文档

- [Next.js 文档](https://nextjs.org/docs)
- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [shadcn/ui 文档](https://ui.shadcn.com)
- [Tailwind CSS 文档](https://tailwindcss.com/docs)
- [apimart.ai](https://apimart.ai)
