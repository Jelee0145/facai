# 模块审查提示词：前端 API 代理层

## 模块概述

前端 API 代理层采用 BFF（Backend For Frontend）模式，所有前端请求通过 Next.js API Routes 转发到 FastAPI 后端。该层负责请求转发、认证注入、熔断保护、重试策略和 SSRF 防护。

## 涉及文件

| 文件 | 职责 | 行数 |
|------|------|------|
| `src/app/api/generate/route.ts` | 生成请求代理 | ~50 |
| `src/app/api/generate/[...path]/route.ts` | 生成子路径代理（异步、状态、流） | ~30 |
| `src/app/api/proxy-image/route.ts` | 安全图片代理（SSRF 防护） | 135 |
| `src/app/api/auth/[...path]/route.ts` | 认证路由代理 | ~20 |
| `src/app/api/admin/[...path]/route.ts` | 管理路由代理 | ~20 |
| `src/app/api/user/[...path]/route.ts` | 用户路由代理 | ~20 |
| `src/app/api/custom-types/route.ts` | 自定义类型 CRUD 代理 | ~30 |
| `src/lib/proxy.ts` | 通用后端代理函数 | 160 |
| `src/lib/fetch.ts` | 指数退避重试 fetch | 34 |
| `src/lib/circuit-breaker.ts` | 熔断器（状态机） | 58 |

## 审查提示词

请对前端 API 代理层进行全面代码审查，重点检查以下方面：

### 1. 安全性（Critical）

- **SSRF 防护**（`proxy-image/route.ts`）：
  - IP 黑名单是否覆盖 IPv4/IPv6 所有私有地址段（RFC 1918、loopback、link-local、metadata）
  - DNS 解析验证是否在实际请求前执行，是否存在 TOCTOU（Time-of-Check to Time-of-Use）竞态
  - HTTPS-only 强制是否可被绕过
  - `redirect: "manual"` 是否能完全防止重定向攻击
  - `metadata.google.internal` 等云元数据端点是否完整覆盖

- **认证注入**（`proxy.ts`）：
  - `API_AUTH_TOKEN` 是否可能通过日志或错误响应泄露
  - 内部 API 认证 token（`X-API-Auth`）是否仅在服务端注入，前端不可篡改
  - Cookie 转发逻辑是否可能将其他域名的 cookie 转发到后端

- **请求体大小限制**：
  - 当前限制为 10MB，是否足够防御 DoS 攻击
  - 大 body 的读取是否会导致内存耗尽

### 2. 熔断器与重试（High）

- **状态机正确性**（`circuit-breaker.ts`）：
  - `CLOSED → OPEN`：连续 5 次失败后进入 OPEN 状态，是否需要区分失败类型（网络错误 vs 4xx）
  - `OPEN → HALF_OPEN`：30 秒超时后进入 HALF_OPEN，是否正确处理并发探针请求
  - `HALF_OPEN → CLOSED/OPEN`：单次成功/失败的转换是否正确
  - 是否存在竞态条件：多个并发请求同时修改 circuit state

- **重试策略**（`fetch.ts`）：
  - 指数退避参数是否合理（base 1s, 3 次重试，最大延迟 4s）
  - 是否应该对 4xx 客户端错误不重试
  - `response.ok` 为 false 但状态码不在可重试集合时，是否应该提前返回

- **熔断器与重试交互**：
  - 熔断器 OPEN 时抛出 `CircuitOpenError`，重试机制是否应该捕获此异常
  - 两者叠加是否会产生预期外的行为

### 3. 代码质量（Medium）

- **冗余代码**（`proxy.ts:77-92`）：
  - `forwardCookies` 为 true 和 false 时的 header 过滤逻辑完全相同，是否为 copy-paste 错误
  - 如果确实需要区分，两个分支应有不同的过滤策略

- **SSE streaming**（`proxy.ts:109-121`）：
  - 仅通过 URL 以 `/stream` 结尾判断是否为 SSE，是否有更可靠的方式
  - SSE 连接的超时和错误处理是否完善
  - 返回的 `Response` 是否正确传递了后端的 `text/event-stream` 编码

- **错误处理**：
  - `proxy.ts` 中 JSON 解析失败时回退为 text 响应，是否应该区分 JSON 和非 JSON 端点
  - 熔断器 OPEN 时返回 503，是否需要包含 `Retry-After` header

### 4. 性能（Low）

- **body 读取**：`request.text()` 会将整个请求体加载到内存，大请求是否有风险
- **DNS 缓存**：`proxy-image` 的 DNS 解析是否应该缓存以避免重复解析
- **连接池**：代理层是否复用 HTTP 连接

## 审查输出格式

请按以下格式输出审查结果：

```
### [严重程度] 问题标题

**文件**: `path/to/file.ts:行号`
**问题**: 问题描述
**建议**: 改进方案
**影响**: 不修改的潜在风险
```

严重程度分级：
- **Critical**: 安全漏洞或数据损坏风险
- **High**: 功能缺陷或可靠性问题
- **Medium**: 代码质量或可维护性问题
- **Low**: 性能优化或最佳实践建议
