# API 参考手册

> 本文档描述后端 FastAPI 服务的全部 API 接口。后端默认运行在 `http://localhost:8001`。
>
> 接口分为**对外接口**（面向前端用户）和**管理接口**（面向管理员后台）两部分。

---

## 目录

- [通用约定](#通用约定)
- [对外接口](#对外接口)
  - [健康检查](#1-健康检查)
  - [用户认证](#2-用户认证)
  - [用户中心](#3-用户中心)
  - [图片生成](#4-图片生成)
  - [自定义产品类型](#5-自定义产品类型)
- [管理接口（内部）](#管理接口内部)
  - [管理员登录](#1-管理员登录)
  - [API Key 管理](#2-api-key-管理)
  - [生成历史](#3-生成历史)
  - [充值套餐管理](#4-充值套餐管理)
  - [订单管理](#5-订单管理)
  - [生成成本配置](#6-生成成本配置)
  - [LLM 配置](#7-llm-配置)
  - [系统健康](#8-系统健康)

---

## 通用约定

### 认证方式

项目有两套独立的认证体系：

| 身份 | Cookie 名 | 说明 |
|------|----------|------|
| 前台用户 | `user_access_token` | 注册/登录后获得，JWT 格式 |
| 管理员 | `access_token` | 管理后台登录后获得，JWT 格式 |

### CSRF 保护

所有写操作（POST/PUT/DELETE）需要在请求头中携带 `X-CSRF-Token`。CSRF Token 的值为 JWT 的 `jti`（JWT ID）声明，在登录响应中返回。

### 请求头

| Header | 说明 | 何时需要 |
|--------|------|---------|
| `Content-Type` | `application/json` | 所有请求体为 JSON 的接口 |
| `X-CSRF-Token` | CSRF Token | 所有写操作 |
| `X-API-Auth` | 内部 API 认证令牌 | 生成类接口（由前端代理层自动添加） |

### 通用错误响应

```json
{
  "detail": "错误描述信息"
}
```

### 通用错误码

| 状态码 | 含义 | 常见原因 |
|--------|------|---------|
| 400 | 请求参数错误 | 输入校验失败、格式不合法 |
| 401 | 未认证 | Cookie 缺失或 Token 过期 |
| 403 | 权限不足 | CSRF token 不匹配、X-API-Auth 验证失败 |
| 404 | 资源不存在 | 任务/订单/Key 不存在 |
| 409 | 冲突 | 用户名已存在、无可用 API Key |
| 413 | 请求体过大 | 图片超过 5MB 限制 |
| 422 | 参数类型错误 | 字段类型不匹配 |
| 429 | 请求过于频繁 | 触发速率限制 |
| 502 | 上游服务异常 | Apimart API 调用失败 |
| 503 | 服务不可用 | API_AUTH_TOKEN 未配置 |

### 速率限制

| 接口 | 限制 | 按什么身份 |
|------|------|-----------|
| `POST /auth/register` | 10 次/分钟 | IP |
| `POST /auth/login` | 10 次/分钟 | IP |
| `POST /api/generate` | 10 次/分钟 | 用户 ID 或 IP |
| `POST /api/generate/async` | 20 次/分钟 | 用户 ID 或 IP |
| `GET /api/generate/status/*` | 30 次/分钟 | 用户 ID 或 IP |
| `POST /api/custom-types` | 30 次/分钟 | 用户 ID 或 IP |
| `POST /admin/login` | 5 次/分钟 | IP |
| 管理接口（写操作） | 10-20 次/分钟 | 管理员 ID 或 IP |

---

## 对外接口

### 1. 健康检查

#### `GET /health`

检查后端服务是否正常运行。

**认证：** 无需认证

**响应：**
```json
{
  "status": "ok"
}
```

---

### 2. 用户认证

#### `POST /auth/register` — 用户注册

**限流：** 10 次/分钟

**请求体：**
```json
{
  "username": "string (3-50 字符)",
  "password": "string (12-128 字符，必须包含大小写字母、数字、特殊字符)",
  "phone": "string (可选, ≤30 字符)",
  "email": "string (可选, ≤120 字符)"
}
```

**成功响应 (200)：**
```json
{
  "user": {
    "id": 1,
    "username": "testuser",
    "phone": "",
    "email": "",
    "is_unlimited": false
  },
  "csrf_token": "jwt-jti-string",
  "wallet": {
    "user_id": 1,
    "balance": 0,
    "total_recharged": 0,
    "total_spent": 0,
    "is_unlimited": false
  }
}
```
同时设置 `user_access_token` Cookie。

**错误响应：**
- `400` — 密码强度不足（缺少大小写/数字/特殊字符/长度不够）
- `409` — 用户名已存在

---

#### `POST /auth/login` — 用户登录

**限流：** 10 次/分钟

**请求体：**
```json
{
  "username": "string",
  "password": "string"
}
```

**成功响应 (200)：**
```json
{
  "user": {
    "id": 1,
    "username": "testuser"
  },
  "csrf_token": "jwt-jti-string",
  "wallet": {
    "user_id": 1,
    "balance": 500,
    "total_recharged": 600,
    "total_spent": 100,
    "is_unlimited": false
  }
}
```

**错误响应：**
- `401` — 用户名或密码错误
- `403` — 账号已被冻结，请联系管理员解封
- `423` — 账号已锁定（连续失败 ≥5 次，锁定 15 分钟）

---

#### `POST /auth/logout` — 用户登出

**认证：** 需要 `user_access_token` Cookie + `X-CSRF-Token`

**成功响应 (200)：**
```json
{
  "message": "logged out"
}
```
同时清除 `user_access_token` Cookie，并吊销当前 JWT。

---

#### `GET /auth/me` — 获取当前用户信息

**认证：** 可选（未登录时返回空用户）

**成功响应 (200)：**
```json
{
  "user": {
    "id": 1,
    "username": "testuser",
    "is_unlimited": false,
    "csrf_token": "jwt-jti-string"
  },
  "wallet": {
    "user_id": 1,
    "balance": 500,
    "is_unlimited": false
  },
  "csrf_token": "jwt-jti-string",
  "generation_cost_points": 10
}
```

未登录时：
```json
{
  "user": null,
  "wallet": null,
  "csrf_token": "",
  "generation_cost_points": 10
}
```

冻结用户时（保持登录态，返回 `status: "frozen"`）：
```json
{
  "user": {
    "id": 1,
    "username": "testuser",
    "is_unlimited": false,
    "status": "frozen"
  },
  "wallet": { "user_id": 1, "balance": 500, "is_unlimited": false },
  "csrf_token": "jwt-jti-string",
  "generation_cost_points": 10
}
```

---

### 3. 用户中心

#### `GET /user/wallet` — 查询积分余额

**认证：** 需要前台用户登录

**响应：**
```json
{
  "wallet": {
    "user_id": 1,
    "balance": 500,
    "total_recharged": 600,
    "total_spent": 100,
    "is_unlimited": false
  },
  "generation_cost_points": 10
}
```

---

#### `GET /user/packages` — 查询可购买套餐

**认证：** 无需认证

**响应：**
```json
{
  "packages": [
    {
      "id": 1,
      "name": "体验包",
      "price_fen": 990,
      "points": 100,
      "bonus_points": 0,
      "status": "active",
      "sort_order": 10
    }
  ]
}
```

---

#### `POST /user/orders` — 创建充值订单

**认证：** 需要前台用户登录 + CSRF

**限流：** 20 次/分钟

**请求体：**
```json
{
  "package_id": 1
}
```

**成功响应 (200)：**
```json
{
  "order": {
    "id": 1,
    "order_no": "MOCK1717200000A1B2C3D4",
    "user_id": 1,
    "package_id": 1,
    "amount_fen": 990,
    "points": 100,
    "status": "pending",
    "package_name": "体验包"
  },
  "payment": {
    "provider": "mock",
    "status": "pending"
  }
}
```

**错误响应：**
- `404` — 套餐不存在或已下架

---

#### `GET /user/orders` — 查询我的订单列表

**认证：** 需要前台用户登录

**响应：**
```json
{
  "orders": [
    {
      "id": 1,
      "order_no": "PAY...",
      "package_name": "体验包",
      "amount_fen": 990,
      "points": 100,
      "status": "submitted",
      "payment_remark": "微信昵称",
      "proof_image": "/uploads/proofs/PAY..._123456.png",
      "submitted_at": "2026-06-02 10:00:05",
      "reject_reason": "",
      "created_at": "2026-06-02 10:00:00"
    }
  ]
}
```

---

#### `POST /user/orders/{order_no}/submit-proof` — 提交付款凭证

**认证：** 需要前台用户登录 + CSRF

**限流：** 10 次/分钟

**请求：** `multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `payment_remark` | string | 否* | 付款备注（微信昵称/转账附言） |
| `proof_image` | file | 否* | 付款截图（JPG/PNG/WebP，≤5MB） |

*至少提供一项。

**状态：** `pending`/`rejected` → `submitted`；已提交的可重新提交覆盖。

---

#### `GET /user/ledger` — 查询积分流水

**认证：** 需要前台用户登录

**响应：**
```json
{
  "items": [
    {
      "id": 1,
      "type": "recharge",
      "direction": "in",
      "points": 100,
      "balance_after": 100,
      "order_id": 1,
      "remark": "充值订单 MOCK...",
      "created_at": "2026-05-30 10:00:05"
    },
    {
      "id": 2,
      "type": "consume",
      "direction": "out",
      "points": 10,
      "balance_after": 90,
      "reference_id": "task-uuid",
      "remark": "生成任务 task-uuid",
      "created_at": "2026-05-30 10:05:00"
    }
  ]
}
```

---

#### `GET /user/history` — 查询生成历史

**认证：** 需要前台用户登录

**响应：**
```json
{
  "items": [
    {
      "id": 1,
      "task_id": "uuid-string",
      "product_type": "连衣裙",
      "description_snapshot": "高品质连衣裙...",
      "preview_images": ["https://..."],
      "charge_points": 10,
      "status": "completed",
      "created_at": "2026-05-30 10:05:00"
    }
  ]
}
```

---

### 4. 图片生成

> **注意：** 生成类接口需要 `X-API-Auth` 请求头（由前端 API 代理层自动注入），不接受外部直接调用。

#### `POST /api/generate` — 同步图片生成

同步生成单张或部分图片（comparison / detail / test 模式）。**完整生成（14 张图）请使用异步接口。**

**认证：** `X-API-Auth` + 前台用户登录 + CSRF

**限流：** 10 次/分钟

**请求体 (GenerateRequest)：**
```json
{
  "image_url": "https://example.com/product.jpg 或 data:image/jpeg;base64,...",
  "product_type": "连衣裙",
  "country": "japan",
  "model": "general",
  "generate_type": "comparison",
  "style_index": 0,
  "prompt_size": "auto",
  "prompt_resolution": "1k"
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `image_url` | string | **必填** | 参考图 URL 或 base64 data URL |
| `product_type` | string | `""` | 产品品类描述（≤200 字符） |
| `country` | string | `"japan"` | 目标国家：`japan/korea/usa/thailand/vietnam/malaysia/philippines/indonesia/china` |
| `model` | string | `"general"` | 模型风格 |
| `generate_type` | string | `"all"` | 生成类型：`comparison/detail/test`（不允许 `all`，请用异步接口） |
| `style_index` | int | `0` | test 模式下的风格索引（0-10） |
| `prompt_size` | string | `"auto"` | 生成尺寸：`auto/1:1/4:3/3:4/16:9/9:16` |
| `prompt_resolution` | string | `"1k"` | 分辨率：`1k/2k/4k` |

**图片限制：**
- 格式：JPEG / PNG / WebP / AVIF
- 最大大小：5MB（base64 解码后）
- 支持 HTTP URL 和 `data:image/*;base64` 格式

**响应示例（comparison 模式）：**
```json
{
  "success": true,
  "data": {
    "comparisonImage": "https://apimart.ai/generated/..."
  }
}
```

**响应示例（test 模式）：**
```json
{
  "success": true,
  "data": {
    "modelImages": ["https://..."],
    "modelStyles": ["日式清新风"],
    "originalImage": "https://apimart.ai/uploaded/...",
    "category": { "name": "连衣裙", "parent": "女装", "shotType": "model" },
    "model": { "code": "japan_fresh", "name": "日式清新风", "tagline": "..." },
    "country": { "name": "日本", "flag": "...", "platform": "TikTok Shop", "language": "ja" },
    "titles": ["..."],
    "tags": ["..."],
    "description": "...",
    "targetAudience": "..."
  }
}
```

**错误响应：**
- `400` — 图片格式不合法、generate_type 为 all
- `402` — 积分不足
- `409` — 无可用 API Key
- `413` — 图片超过 5MB
- `502` — Apimart API 调用失败

**积分扣费：** 生成前预扣积分，失败时自动退回。

---

#### `POST /api/generate/async` — 异步图片生成

启动后台任务生成全部 14 张图，立即返回 `task_id`。推荐客户端通过 SSE 持续接收进度；轮询接口仅作为状态查询/排障补充。

**认证：** `X-API-Auth` + 前台用户登录 + CSRF

**限流：** 20 次/分钟

**请求体：** 同 `POST /api/generate`

**成功响应 (200)：**
```json
{
  "task_id": "uuid-string",
  "charge_points": 10
}
```

**错误响应：**
- `402` — 积分不足
- `409` — 无可用 API Key

---

#### `GET /api/generate/status/{task_id}` — 查询任务进度

**认证：** `X-API-Auth` + 前台用户登录（仅任务创建者可查询）

**限流：** 30 次/分钟

**响应：**
```json
{
  "status": "generating",
  "total": 14,
  "completed": 5,
  "elapsed_seconds": 45.2,
  "images": [
    {
      "index": 0,
      "status": "completed",
      "url": "https://...",
      "name": "模特图1"
    },
    {
      "index": 1,
      "status": "pending",
      "url": null,
      "name": "模特图2"
    }
  ],
  "result": null,
  "error": null
}
```

**任务状态值：**

| status | 含义 |
|--------|------|
| `submitting` | 任务提交中 |
| `generating` | 图片生成中 |
| `completed` | 全部完成 |
| `error` / `failed` | 任务失败 |

---

#### `GET /api/generate/status/{task_id}/stream` — SSE 实时进度流

通过 Server-Sent Events 实时接收任务进度推送。

**认证：** `X-API-Auth` + 前台用户登录（仅任务创建者可连接）

**响应格式：** `text/event-stream`

每个事件格式：
```
data: {"status":"generating","total":14,"completed":3,"images":[...]}\n\n
```

**事件类型：**

| 事件 status | 含义 | 包含字段 |
|-------------|------|---------|
| `submitting` | 任务初始化 | `total`, `completed` |
| `generating` | 生成中 | `total`, `completed`, `images[]` |
| `completed` | 全部完成 | `result`（完整生成结果） |
| `failed` | 失败 | `error` |

**连接行为：**
- 连接建立时先收到当前任务快照；如果任务已完成，客户端会立即拿到 `completed` 结果
- 空闲保活：长时间无进展时服务端会发送 SSE keep-alive comment，连接保持打开
- 终态断开：收到 `completed`/`failed`/`error` 后自动结束流
- 客户端应持续自动重连，直到收到后端终态或确认会话过期

**使用示例（JavaScript）：**
```javascript
const eventSource = new EventSource('/api/generate/status/TASK_ID/stream');
eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log(`进度: ${data.completed}/${data.total}`);
  if (data.status === 'completed') {
    eventSource.close();
  }
};
```

---

### 5. 自定义产品类型

#### `GET /api/custom-types` — 查询自定义类型列表

**认证：** 无需认证

**响应：**
```json
{
  "types": [
    {
      "id": 1,
      "label": "蓝牙耳机",
      "category": "自定义",
      "created_at": "2026-05-30 10:00:00"
    }
  ]
}
```

---

#### `POST /api/custom-types` — 新增自定义类型

**限流：** 30 次/分钟

**请求体：**
```json
{
  "label": "蓝牙耳机",
  "category": "电子产品"
}
```

**响应：**
```json
{
  "id": 1,
  "label": "蓝牙耳机",
  "category": "电子产品"
}
```

---

#### `DELETE /api/custom-types/{type_id}` — 删除自定义类型

**限流：** 30 次/分钟

**成功响应：**
```json
{
  "message": "删除成功"
}
```

**错误响应：**
- `404` — 类型不存在

---

## 管理接口（内部）

> 以下接口仅供管理后台使用，需要管理员身份认证。
>
> Cookie 名：`access_token`。所有写操作需要 `X-CSRF-Token`。

### 1. 管理员登录

#### `POST /admin/login`

**限流：** 5 次/分钟

**请求体：**
```json
{
  "username": "admin",
  "password": "your-strong-password"
}
```

**成功响应：**
```json
{
  "user": { "sub": "admin", "role": "admin" },
  "access_token": "jwt-string",
  "token_type": "bearer",
  "csrf_token": "jwt-jti-string"
}
```

#### `GET /admin/me` — 获取当前管理员信息

#### `POST /admin/refresh` — 刷新 Token（旧 Token 被吊销）

#### `POST /admin/logout` — 登出（清除 Cookie + 吊销 Token）

---

### 2. API Key 管理

#### `GET /admin/api-keys` — 列出所有 API Key（脱敏）

**响应：**
```json
{
  "keys": [
    {
      "id": 1,
      "key_value": "sk-a****xyz",
      "name": "默认 Key",
      "is_active": 1,
      "daily_limit": 200,
      "today_used": 5,
      "total_used": 100,
      "fail_count": 0,
      "balance_usd": 10.5,
      "total_balance_usd": 50.0
    }
  ]
}
```

#### `POST /admin/api-keys` — 添加 API Key

```json
{
  "key_value": "sk-...",
  "name": "Key 名称",
  "daily_limit": 200
}
```

#### `PUT /admin/api-keys/{key_id}` — 更新 API Key

```json
{
  "name": "新名称",
  "is_active": 1,
  "daily_limit": 300,
  "balance_usd": 15.0
}
```

#### `DELETE /admin/api-keys/{key_id}` — 删除 API Key

---

### 3. 用户管理

#### `POST /admin/users` — 管理员创建用户

**限流：** 20 次/分钟

**请求体：**
```json
{
  "username": "string (3-50 字符)",
  "password": "string (1-128 字符)",
  "phone": "string (可选, ≤30 字符)",
  "email": "string (可选, ≤120 字符)",
  "note": "string (可选, ≤500 字符)",
  "is_unlimited": false
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `username` | string | 是 | 用户名（3-50 字符） |
| `password` | string | 是 | 密码（无需满足强密码策略） |
| `phone` | string | 否 | 手机号 |
| `email` | string | 否 | 邮箱 |
| `note` | string | 否 | 备注 |
| `is_unlimited` | boolean | 否 | 是否无限额度（默认 false，不扣积分） |

**成功响应：**
```json
{
  "id": 1,
  "username": "testuser"
}
```

**错误响应：**
- `400` — 密码为空
- `409` — 用户名已存在

---

### 4. 生成历史

#### `GET /admin/history` — 查询生成历史（分页）

**查询参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `page` | 1 | 页码 |
| `per_page` | 20 | 每页条数 |
| `status` | `""` | 筛选状态 |
| `search` | `""` | 搜索关键词（品类/task_id） |

**响应：**
```json
{
  "total": 100,
  "page": 1,
  "per_page": 20,
  "items": [
    {
      "id": 1,
      "task_id": "uuid",
      "product_type": "连衣裙",
      "country": "japan",
      "status": "completed",
      "success_count": 14,
      "elapsed_seconds": 120.5,
      "key_name": "默认 Key",
      "created_at": "..."
    }
  ]
}
```

#### `GET /admin/history/{history_id}` — 获取单条历史详情

JSON 字段（`llm_request`, `llm_response`, `tasks_detail`）自动解析为对象返回。

---

### 5. 充值套餐管理

#### `GET /admin/credit-packages` — 查询所有套餐（含下架）

#### `POST /admin/credit-packages` — 创建套餐

```json
{
  "name": "新套餐",
  "price_fen": 990,
  "points": 100,
  "bonus_points": 10,
  "status": "active",
  "sort_order": 50
}
```

#### `PUT /admin/credit-packages/{package_id}` — 更新套餐

请求体同创建。

---

### 6. 订单管理

#### `GET /admin/orders` — 查询全部订单

返回所有订单，包含新字段：`payment_remark`、`proof_image`、`submitted_at`、`reject_reason`、`reviewer_note`。

#### `POST /admin/orders/{order_no}/mark-paid` — 确认入账

管理员核验凭证后确认入账，积分充入用户钱包。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `reviewer_note` | string | 否 | 审核备注 |

支持从 `pending`、`submitted`、`paid` 状态转入 `credited`。

#### `POST /admin/orders/{order_no}/reject` — 驳回订单

驳回用户提交的付款凭证。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `reject_reason` | string | 是 | 驳回原因（用户可见） |

状态从 `submitted`/`pending` → `rejected`。用户可重新提交凭证。

---

### 7. 生成成本配置

#### `PUT /admin/generation-cost` — 更新每次生成扣费积分

```json
{
  "points": 10
}
```

---

### 8. LLM 配置

#### `GET /admin/llm-config` — 获取 LLM 配置（Key 脱敏）

**响应：**
```json
{
  "api_key": "sk-****abc",
  "has_key": true,
  "key_length": 32,
  "model": "qwen3-vl-flash"
}
```

#### `PUT /admin/llm-config` — 更新 LLM 配置

```json
{
  "api_key": "sk-...",
  "model": "qwen3-vl-plus"
}
```

#### `POST /admin/llm-config/test` — 测试 LLM 连接

**限流：** 5 次/分钟

**响应：**
```json
{
  "success": true,
  "reply": "连接测试成功，模型已就绪"
}
```

---

### 9. 系统健康

#### `GET /admin/health` — 系统健康状态

**响应：**
```json
{
  "status": "healthy",
  "server_time": "2026-05-30T10:00:00",
  "task_store_size": 3,
  "keys_health": {
    "total": 3,
    "active": 2,
    "disabled": 1
  }
}
```

#### `GET /admin/dashboard` — 仪表盘概览

**响应：**
```json
{
  "total_keys": 3,
  "active_keys": 2,
  "today_generations": 50,
  "today_success": 48,
  "today_success_rate": 96.0,
  "today_avg_time": 85.3,
  "total_generations": 1000,
  "keys_health": { "total": 3, "active": 2, "disabled": 1 }
}
```
