# 模块审查提示词：前端基础设施

## 模块概述

前端基础设施层提供跨模块的通用功能，包括安全头注入、自定义 HTTP Server、SSE 连接 Hook、日志工具和通用工具函数。

## 涉及文件

| 文件 | 职责 | 行数 |
|------|------|------|
| `src/middleware.ts` | Next.js 中间件（CSP、安全头） | 42 |
| `src/server.ts` | 自定义 HTTP Server（端口 4524） | ~80 |
| `src/lib/logger.ts` | 开发环境日志工具 | ~30 |
| `src/lib/use-sse.ts` | SSE 连接 React Hook | 84 |
| `src/lib/utils.ts` | cn() 工具函数 | ~10 |

## 审查提示词

请对前端基础设施进行全面代码审查，重点检查以下方面：

### 1. 安全性（Critical）

- **CSP 策略**（`middleware.ts`）：
  - 开发模式允许 `'unsafe-inline' 'unsafe-eval'`，是否生产环境也存在类似问题
  - `img-src` 是否需要支持外部图片域名（如 CDN）
  - `connect-src` 在生产环境是否需要支持后端 URL
  - CSP 是否需要包含 `upgrade-insecure-requests`

- **安全头配置**：
  - `X-Frame-Options: DENY` 是否会导致嵌入式场景（如 iframe 嵌入）问题
  - `Permissions-Policy` 是否需要更细粒度的控制
  - `Strict-Transport-Security` 的 `includeSubDomains` 是否会影响子域名
  - 是否缺少 `X-XSS-Protection`（现代浏览器已弃用但仍建议设置）

- **Server（`server.ts`）**：
  - 自定义 server 是否会绕过 Next.js 内置的安全中间件
  - 是否需要监听特定的错误事件

### 2. SSE Hook 可靠性（High）

- **重连逻辑**（`use-sse.ts`）：
  - 最大重连次数（3 次）和间隔（5s）是否合理
  - 重连计数器在收到有效消息时重置，是否应该在连接成功时重置
  - 重连失败后是否应该给用户明确的提示

- **资源清理**：
  - `cleanup` 函数是否正确处理所有边缘情况（组件卸载时、taskId 变化时）
  - `closed` 标志位是否能防止所有竞态条件
  - `timeoutId` 的清理是否完整

- **闭包陷阱**：
  - `handlersRef` 模式是否正确避免了 useEffect 的闭包问题
  - 是否应该使用 `useCallback` 包装 handlers

- **EventSource 状态**：
  - 是否需要监听 `readyState` 变化
  - `EventSource` 的 `withCredentials` 是否需要配置

### 3. 自定义 Server（High）

- **优雅关机**（`server.ts`）：
  - 5 秒超时后强制关闭是否足够（是否需要可配置）
  - 是否需要处理 `uncaughtException` 和 `unhandledRejection`
  - 进程退出码是否正确

- **端口管理**：
  - 端口冲突时的错误处理
  - 是否需要支持端口自动分配

### 4. 日志系统（Medium）

- **生产环境日志**（`logger.ts`）：
  - 生产环境完全静默是否合适，是否应该保留 error 级别
  - 是否需要支持结构化日志
  - 日志是否应该写入文件而非仅 console

- **开发环境日志**：
  - 日志格式是否包含时间戳
  - 是否需要日志级别控制

### 5. 代码质量（Low）

- **工具函数**（`utils.ts`）：
  - `cn()` 函数是否被正确使用
  - 是否有其他常用的工具函数应该抽取

- **类型定义**：
  - 共享类型是否应该集中定义
  - 是否有缺失的类型定义

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
- **Critical**: 安全漏洞
- **High**: 可靠性或功能缺陷
- **Medium**: 代码质量或可维护性问题
- **Low**: 最佳实践建议
