# Code Review 100 - Status Tracker

> Last updated: 2026-05-28 (Round 2)

## Baseline

**All checks green:** Python compile (6 files), TypeScript compile, 6 test suites (64 tests total):
- `test_refund_idempotency` — PASS
- `test_task_authorization` — PASS
- `test_task_store` — PASS
- `test_llm_provider` — 9/9 PASS
- `test_auth_security` — 17/17 PASS
- `test_async_task_tracking` — 5/5 PASS

## Round 2 Fixes Applied

| Issue | Fix | Files |
|---|---|---|
| Proxy-image Content-Type missing → defaulted to image/png | Fail-closed: missing CT → 415; removed SVG; added magic bytes check | `proxy-image/route.ts` |
| Proxy-image streaming / size cap | `readStreamWithCap()` with cumulative byte counting | `proxy-image/route.ts` |
| DNS TOCTOU | Post-fetch `resp.url` hostname check; redirect:manual retained | `proxy-image/route.ts` |
| LLM schema validation fallback to raw dict | `_parse_llm_json` returns `None` on schema failure, no raw-dict fallback | `llm_provider.py` |
| JWT revocation fail-open | `verify_token` returns `None` on missing jti or DB error | `security.py` |
| `_active_tasks` no done-callback | `task.add_done_callback(_cleanup_active_task)` with exception handling | `main.py` |
| Password min length 8 → 12 | `PASSWORD_MIN_LENGTH = 12` constant; `validate_password_strength` uses it | `security.py`, `main.py` |

## Status by Item

| # | Description | Status | Notes |
|---|---|---|---|
| 1 | Key index out of bounds after disable | to-fix | Phase 4 |
| 2 | threading.Lock in asyncio | deferred | Current single-threaded asyncio is acceptable |
| 3 | mark_success clears fail_count | fixed | Phase 4: `fail_count = MAX(fail_count - 1, 0)` |
| 4 | mark_failure doesn't distinguish auth/network | deferred | Current design counts all failures toward threshold |
| 5 | health_check excludes disabled keys | to-fix | Low priority |
| 6 | reset_daily_usage no caller | to-fix | Phase 4 |
| 7 | get_active_key no TypedDict | deferred | Code style |
| 8 | No unit tests for key_manager | to-fix | Add in Phase 4 |
| 9 | Global singleton no lazy load | deferred | Works in practice |
| 10 | defaultdict iteration safety | fixed | Phase 3: copy list before iterating |
| 11 | No expired task_id cleanup | fixed | Phase 3: cleanup on unsubscribe, empty queue removal |
| 12 | push_event sync in async | deferred | put_nowait is non-blocking |
| 13 | QueueFull silently drops events | fixed | Phase 3: terminal events evict oldest non-terminal |
| 14 | 300s timeout hardcoded | fixed | Phase 3: SSE_IDLE_TIMEOUT_SECONDS env var |
| 15 | No asyncio.Lock on subscribe/unsubscribe | fixed | Phase 3: async lock on subscribe/unsubscribe |
| 16 | No logging in sse.py | fixed | Phase 3: logger.debug/warning added |
| 17 | No unit tests for sse.py | to-fix | Deferred |
| 18 | Type annotations incomplete | fixed | Phase 3: `asyncio.Queue[dict]` added |
| 19 | CSP connect-src missing backend URL | deferred | Requires middleware changes |
| 20 | SSE reconnect counter reset timing | fixed | Phase 6: reset on onopen callback |
| 21 | No uncaughtException handler | deferred | Infrastructure concern |
| 22 | img-src missing external domains | deferred | CSP configuration |
| 23 | No upgrade-insecure-requests | deferred | CSP configuration |
| 24 | Missing SSE onopen callback | fixed | Phase 6: onopen handler added |
| 25 | handlersRef race | deferred | React hook pattern, low risk |
| 26 | X-XSS-Protection not set | deferred | Header config |
| 27 | Parse error silently ignored | fixed | Phase 6: console.warn on parse error |
| 28 | 5s shutdown timeout not configurable | deferred | Low priority |
| 29 | No reject new connections on shutdown | deferred | Low priority |
| 30 | No log level control | deferred | Low priority |
| 31 | page.tsx 1600+ lines | deferred | Major refactor |
| 32 | 30+ useState scattered | deferred | Major refactor |
| 33 | No useMemo/useCallback | deferred | Performance optimization |
| 34 | elapsedSeconds never increments | deferred | UI fix |
| 35 | Error messages expose technical details | to-fix | Phase 6 (deferred — requires UX review) |
| 36 | Hardcoded numbers | deferred | Code style |
| 37 | generationStatus no type safety | deferred | Code style |
| 38 | Lightbox no keyboard nav | deferred | UX improvement |
| 39 | Missing aria-label | deferred | Accessibility |
| 40 | COUNTRIES platform field unused | deferred | Code cleanup |
| 41 | ImageGallery unused component | deferred | Code cleanup |
| 42 | Contrast ratio concerns | deferred | Accessibility |
| 43 | SSRF TOCTOU race | partial | Round 2: post-fetch resp.url check + redirect:manual. Residual risk: DNS rebinding between resolve and fetch cannot be fully mitigated with standard fetch. |
| 44 | Incomplete blocked hostnames | fixed | Round 1+2: expanded list, normalizeHostname, trailing-dot handling |
| 45 | DNS failure silently ignored | fixed | Round 1: fail-closed on both v4+v6 failure |
| 46 | Circuit breaker no concurrency protection | deferred | Single-threaded JS |
| 47 | SSE bypasses circuit breaker | fixed | Phase 6: SSE stream uses withCircuitBreaker |
| 48 | Circuit breaker OPEN no Retry-After | fixed | Phase 6: Retry-After: 30 header added |
| 49 | custom-types route bypasses proxy | deferred | Low impact |
| 50 | Header filtering redundant | fixed | Phase 6: explicit stripHeaders set |
| 51 | SSE detection by URL suffix | fixed | Phase 6: Accept header + URL suffix check |
| 52 | proxy-image full memory read | fixed | Round 2: readStreamWithCap with cumulative byte counting, 16-byte magic header |
| 53 | Body read no early abort | deferred | Low impact |
| 54 | fetchWithRetry 4xx readability | deferred | Code style |
| 55 | HALF_OPEN no probe limit | deferred | Low impact |
| 56 | Logger silent in production | deferred | Infrastructure |
| 57 | No token revocation | fixed | Round 1+2: revoked_tokens table, jti check in verify_token, fail-closed on DB error |
| 58 | No password complexity | fixed | Round 1+2: validate_password_strength (12-128, mixed case, digit, special) |
| 59 | bcrypt rounds=14 too high | fixed | Round 1: BCRYPT_ROUNDS = 12 |
| 60 | Token naive datetime | deferred | Works with pyjwt |
| 61 | No iss/aud validation | deferred | Low risk |
| 62 | No refresh token rotation | fixed | Phase 2: admin_refresh revokes old jti |
| 63 | Lock constants inconsistent | fixed | Phase 2: database.py imports from security.py |
| 64 | No IP-level tracking | deferred | Low priority |
| 65 | CSRF based on JWT jti | deferred | Works in practice |
| 66 | No CSRF on user routes | deferred | Covered by SameSite cookie |
| 67 | Rate limit config scattered | deferred | Code style |
| 68 | 24h token expiry | deferred | Business decision |
| 69 | No password max length | fixed | Round 1+2: PASSWORD_MAX_LENGTH = 128 constant |
| 70 | No lock exponential backoff | deferred | Enhancement |
| 71 | Rate limit response no Retry-After | deferred | Enhancement |
| 72 | sanitize_input only strip+length | fixed | Phase 5: control char filtering + injection rejection |
| 73 | login/login_customer duplicate code | deferred | Code style |
| 74 | Sync sqlite3 blocks event loop | deferred | Major refactor |
| 75 | threading.local in asyncio | deferred | Major refactor |
| 76 | mark_key_failed TOCTOU | fixed | Phase 4: single SQL atomic UPDATE with CASE WHEN |
| 77 | mark_order_paid manual BEGIN/ROLLBACK | deferred | Works with current pattern |
| 78 | API Key plaintext storage | deferred | Requires encryption infra |
| 79 | init_db no version management | deferred | Enhancement |
| 80 | Dashboard multiple COUNT queries | deferred | Performance |
| 81 | Missing indexes | fixed | Phase 4: 7 indexes added in init_db |
| 82 | INSERT OR REPLACE risks | fixed | Phase 4: UPSERT with ON CONFLICT DO UPDATE |
| 83 | ensure_customer race condition | deferred | Low impact |
| 84 | database.py 940 lines | deferred | Major refactor |
| 85 | Duplicate json import | fixed | Phase 4: removed duplicate imports |
| 86 | WAL checkpoint unmanaged | deferred | Enhancement |
| 87 | Client-side route guard bypass | deferred | Requires middleware changes |
| 88 | 401 response race | deferred | Admin-only concern |
| 89 | Admin login no frontend validation | deferred | Admin-only concern |
| 90 | API Key form no validation | deferred | Admin-only concern |
| 91 | LLM key transmitted in test | deferred | Admin-only concern |
| 92 | Token refresh not implemented | deferred | Admin-only concern |
| 93 | History pagination no URL state | deferred | Enhancement |
| 94 | Billing load duplicate | deferred | Code style |
| 95 | Delete confirm inconsistent | deferred | Code style |
| 96 | No double-click protection | deferred | UX improvement |
| 97 | FormData content-type override | deferred | Edge case |
| 98 | Error type narrowing | deferred | Code style |
| 99 | Sidebar highlight exact match | deferred | UX improvement |
| 100 | Task lifecycle unmanaged | fixed | Round 1+2: _active_tasks set, done_callback with exception handling, recovery marks failed |
| 101 | Refund race condition | fixed | Already fixed before this session |
| 102 | Global exception handler re-raise | fixed | Already fixed before this session |
| 103 | validate_image_data no magic bytes | fixed | Round 1+2: magic bytes in backend + proxy-image stream read |
| 104 | verify_api_auth timing attack | fixed | Already fixed before this session |
| 105 | Sync generate blocks worker | fixed | Already fixed before this session |
| 106 | SSE no user auth | fixed | Already fixed before this session |
| 107 | update_llm_config bypasses abstraction | fixed | Phase 4: uses set_config for all values |
| 108 | mask_api_key duplicate | fixed | Phase 4: main.py imports from database.py |
| 109 | PUT admin/api-keys no Pydantic | deferred | Admin-only concern |
| 110 | add_history sync write failure | deferred | Low risk |
| 111 | @app.on_event deprecated | deferred | Enhancement |
| 112 | Prompt injection blacklist incomplete | fixed | Phase 5: Chinese keywords, DANG patterns added |
| 113 | LLMOutput schema unused | fixed | Round 1+2: LLMOutput.model_validate() in _parse_llm_json, no raw-dict fallback |
| 114 | LLM timeout 30s too short | deferred | Business decision |
| 115 | match_category fixed priority | deferred | Enhancement |
| 116 | prompts_v2.py 892 lines | deferred | Major refactor |
| 117 | Config hardcoded in Python | deferred | Enhancement |
| 118 | Duplicate image_url processing | deferred | Code style |
| 119 | sanitize truncates instead of rejects | fixed | Phase 5: PromptValidationError raised on injection |
| 120 | LLM output no XSS filtering | fixed | Phase 5: LLMOutput schema validation + plain text output |
| 121 | LLM error no temp/perm distinction | deferred | Enhancement |
| 122 | json.loads no code fence stripping | fixed | Phase 5: _CODE_FENCE_RE strips fences |
| 123 | sanitize_prompt_input entry not unified | fixed | Phase 5: centralized in generate_all_tasks entry |
| 124 | Country config ethnicity descriptions | deferred | Content review |
| 125 | LLM shot_type override scope | deferred | Enhancement |
| 126 | print() instead of logging | deferred | Code style |
| 127 | FRONTEND_MODEL_MAP overlap | deferred | Business decision |
