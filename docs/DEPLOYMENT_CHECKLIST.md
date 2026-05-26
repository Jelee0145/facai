# 部署安全检查清单

## 前置条件

- [ ] HTTPS 在反向代理层终结（nginx / Caddy / Cloudflare）
- [ ] `JWT_SECRET` 设置为强随机值（非默认值 `change-me-in-production`）
- [ ] `API_AUTH_TOKEN` 设置为强随机值（`NODE_ENV=production` 时必需）
- [ ] `CORS_ORIGINS` 设置为实际前端域名
- [ ] `NODE_ENV` 设置为 `production`
- [ ] 管理后台密码由 `secrets.token_urlsafe(12)` 随机生成，无默认密码
- [ ] `data.db` 移出源码目录（如 `/var/data/`）
- [ ] `.env` 文件权限设置为 600
- [ ] 删除 `.env.example` 中的敏感默认值

## 运行时加固

- [ ] 每月轮换 `JWT_SECRET`
- [ ] 每日备份 `data.db` 到异地存储
- [ ] 监控：登录失败阈值告警（5次/分/IP）
- [ ] 监控：API 调用量异常告警
- [ ] 监控：后端断路器触发告警（连续 5 次失败后进入 30s 冷却）
- [ ] 检查日志中无敏感信息泄漏
- [ ] 验证 SSE 端点 `/api/generate/status/{task_id}/stream` 可正常推送实时状态
- [ ] 状态变更端点（POST/PUT/DELETE）已在客户端携带 `X-CSRF-Token` 请求头
- [ ] Docker 部署确认 `Dockerfile.backend` 以 `USER appuser` 非 root 用户运行
- [ ] 确认 `NODE_ENV=production` 时 `console.error` 由 `src/lib/logger.ts` 静默处理

## 构建检查

- [ ] `pnpm lint` 无 error（warning 可接受）
- [ ] `pnpm ts-check` 通过
- [ ] `scripts/build.sh` 构建成功
- [ ] 运行 `python backend/test_security.py` 全部通过

## CSP 策略（已内置于 `src/middleware.ts`，详见）

- 开发环境（`NODE_ENV !== 'production'`）允许 `'unsafe-inline'` 以支持 Next.js HMR
- 生产环境自动移除 `'unsafe-inline'`，依赖 nonce 或 hash

```
default-src 'self'
script-src 'self'
style-src  'self'
img-src    'self' data: blob:
font-src   'self'
connect-src 'self'
frame-src  'none'
object-src 'none'
base-uri   'self'
form-action 'self'
```

## 速率限制（已内置于 `backend/middleware.py`）

| 端点 | 限制 |
|------|------|
| `POST /api/generate` | 10/min per IP |
| `POST /api/generate/async` | 20/min per IP |
| `POST /admin/login` | 5/min per IP |
| `GET /admin/dashboard` | 30/min per IP |
| `PUT/POST/DELETE /admin/api-keys` | 10/min per IP |

## JWT 配置

- 算法: HS256
- 过期: 7 天
- 存储: HttpOnly Cookie (`access_token`), SameSite=Lax, Path=/
- 生产环境: Cookie `Secure` 标志自动启用（当 `NODE_ENV=production`）
