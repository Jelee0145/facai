# 模块审查提示词：后端安全与认证

## 模块概述

后端安全层提供 JWT 认证、bcrypt 密码加密、暴力破解防护、CSRF 保护和 API 限流功能。支持管理员和普通用户两套独立的认证流程。

## 涉及文件

| 文件 | 职责 | 行数 |
|------|------|------|
| `backend/security.py` | JWT 认证、bcrypt 加密、登录/注册、防暴力破解 | 202 |
| `backend/csrf.py` | CSRF token 验证（基于 JWT jti） | 30 |
| `backend/middleware.py` | 限流中间件（slowapi，基于用户/IP） | 42 |

## 审查提示词

请对后端安全与认证模块进行全面代码审查，重点检查以下方面：

### 1. JWT 安全（Critical）

- **Token 签发**：
  - `create_token` 使用 `datetime.now(timezone.utc)` 但 `.replace(tzinfo=None)` 是否正确（PyJWT 要求 naive datetime）
  - Token 过期时间（1 天）是否合理
  - JTI（UUID v4）是否足够唯一
  - 是否需要 Token 版本控制

- **Token 验证**：
  - `verify_token` 是否验证所有必要字段（exp, iat, sub, role）
  - 是否需要验证 `iss` 和 `aud` claim
  - 过期 Token 的错误消息是否泄露信息

- **Refresh Token**：
  - `refresh_token` 仅基于旧 payload 重新签发，是否安全
  - 是否应该支持 refresh token rotation
  - 旧 Token 在刷新后是否应该失效

- **Token 撤销**：
  - 当前没有 Token 黑名单机制，登出后 Token 是否仍然有效
  - 是否需要支持强制登出
  - JTI 是否用于 token 撤销

### 2. 密码安全（High）

- **bcrypt 配置**：
  - `rounds=14` 是否过高（通常 12 足够，每增加 1 轮时间翻倍）
  - 是否影响登录响应时间
  - 是否需要根据服务器性能调整

- **密码策略**：
  - 是否强制密码复杂度（长度、字符类型）
  - 密码历史检查（防止重复使用）
  - 密码过期策略

- **密码存储**：
  - 密码哈希是否安全存储
  - 是否需要定期轮换 bcrypt rounds

### 3. 暴力破解防护（High）

- **锁定策略**：
  - 5 次失败锁定 15 分钟是否合理
  - 锁定计数是否应该区分 IP/用户（防止锁定合法用户）
  - 是否需要递增锁定时间（指数退避）

- **记录机制**：
  - `record_login_attempt` 在成功后是否重置计数
  - 锁定时间的计算是否正确
  - 是否需要记录失败原因

- **绕过防护**：
  - 是否可以通过注册新账号绕过锁定
  - 是否需要 IP 级别的锁定

### 4. CSRF 防护（Medium）

- **方案选择**：
  - 基于 JWT jti 的 CSRF 防护是否足够安全
  - 是否应该使用 SameSite cookie 属性
  - 双重提交 Cookie 方案的变体

- **覆盖范围**：
  - 当前仅 admin 路由使用 CSRF，用户路由是否也需要
  - GET 请求是否需要 CSRF 保护（通常不需要）
  - 跨域请求的处理

### 5. 限流（Medium）

- **限流粒度**：
  - 基于用户/IP 的限流是否合理
  - 是否需要更细粒度的限流（如 per-endpoint）
  - 不同端点的限流阈值是否应该不同

- **配置**：
  - 限流阈值是否可配置
  - 是否支持突发流量（burst）
  - 限流响应的 `Retry-After` header

### 6. 输入消毒（Medium）

- **sanitize_input**：
  - 长度限制（500）是否足够
  - 是否需要过滤特殊字符
  - 是否需要处理 Unicode 滥用

- **密码输入**：
  - 密码是否应该限制最大长度
  - 是否需要处理 null bytes

### 7. 代码质量（Low）

- **错误消息**：
  - 所有 HTTPException 的 detail 是否用户友好
  - 是否泄露实现细节

- **类型安全**：
  - 函数参数和返回值的类型标注
  - Optional 处理

## 审查输出格式

请按以下格式输出审查结果：

```
### [严重程度] 问题标题

**文件**: `backend/xxx.py:行号`
**问题**: 问题描述
**建议**: 改进方案
**影响**: 不修改的潜在风险
```

严重程度分级：
- **Critical**: 安全漏洞或数据泄露风险
- **High**: 认证/授权缺陷
- **Medium**: 代码质量或安全最佳实践
- **Low**: 建议改进
