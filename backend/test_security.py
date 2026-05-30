"""Security acceptance tests against a running backend service."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


BASE = os.getenv("TEST_BASE", "http://localhost:8001").rstrip("/")
ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent
PASS = 0
FAIL = 0


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


ENV = {**load_env(ROOT / ".env"), **load_env(BACKEND_DIR / ".env")}
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD") or ENV.get("ADMIN_PASSWORD", "")
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN") or ENV.get("API_AUTH_TOKEN", "")
EXPECTED_CORS_ORIGIN = (os.getenv("CORS_ORIGINS") or ENV.get("CORS_ORIGINS") or "http://localhost:4524").split(",")[0].strip()
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() in ("true", "1", "yes")
SESSION_COOKIE = ""
SESSION_CSRF = ""

# Test customer credentials (fixed for idempotent re-runs)
TEST_USER_USERNAME = os.getenv("TEST_USER_USERNAME", "security-test-user")
TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD", "Test!User1Pass")
USER_SESSION_COOKIE = ""
USER_SESSION_CSRF = ""


def test(name: str, fn):
    global PASS, FAIL
    try:
        fn()
        print(f"  PASS  {name}")
        PASS += 1
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        FAIL += 1
    except Exception as e:
        print(f"  FAIL  {name}: {e}")
        FAIL += 1


def hdr(headers, key: str) -> str:
    lower = key.lower()
    for k, v in headers.items():
        if k.lower() == lower:
            return v
    return ""


def req(method: str, path: str, body=None, extra_headers=None, origin=None, cors_method=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        r.add_header("Content-Type", "application/json")
    if origin:
        r.add_header("Origin", origin)
    if cors_method:
        r.add_header("Access-Control-Request-Method", cors_method)
    if extra_headers:
        for k, v in extra_headers.items():
            r.add_header(k, v)
    try:
        resp = urllib.request.urlopen(r, timeout=10)
        raw = resp.read()
        return resp.status, parse_body(raw, resp.headers), dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, parse_body(raw, e.headers), dict(e.headers)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach {url}: {e.reason}") from e


def parse_body(raw: bytes, headers) -> object:
    content_type = hdr(headers, "Content-Type")
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type:
        return json.loads(text) if text else {}
    return text


def check(val, exp, msg: str = ""):
    if val != exp:
        raise AssertionError(f"expected {exp!r}, got {val!r}. {msg}")


def check_in(val, col, msg: str = ""):
    if val not in col:
        raise AssertionError(f"expected {val!r} in {col}. {msg}")


def check_in_text(val: str, text: str, msg: str = ""):
    if val.lower() not in text.lower():
        raise AssertionError(f"expected {val!r} in {text!r}. {msg}")


def login() -> tuple[str, str]:
    if not ADMIN_PASSWORD:
        raise AssertionError("ADMIN_PASSWORD is missing from environment or backend/.env")
    status, body, headers = req("POST", "/admin/login", {"username": "admin", "password": ADMIN_PASSWORD})
    if status == 500:
        resp_body = body if isinstance(body, str) else json.dumps(body)
        raise AssertionError(f"admin login returned 500 (bad hash?): {resp_body[:200]}")
    check(status, 200, "admin login failed")
    if not isinstance(body, dict):
        raise AssertionError("login response is not JSON")
    cookie = hdr(headers, "Set-Cookie").split(";", 1)[0]
    csrf = str(body.get("csrf_token") or "")
    if not cookie or not csrf:
        raise AssertionError("login did not return cookie and csrf_token")
    return cookie, csrf


def session() -> tuple[str, str]:
    global SESSION_COOKIE, SESSION_CSRF
    if not SESSION_COOKIE or not SESSION_CSRF:
        SESSION_COOKIE, SESSION_CSRF = login()
    return SESSION_COOKIE, SESSION_CSRF


def customer_session() -> tuple[str, str]:
    """Register (idempotent) and login a test customer. Returns (cookie_header, csrf_token)."""
    global USER_SESSION_COOKIE, USER_SESSION_CSRF
    if USER_SESSION_COOKIE and USER_SESSION_CSRF:
        return USER_SESSION_COOKIE, USER_SESSION_CSRF

    # Register — ignore if already exists
    req("POST", "/auth/register", {
        "username": TEST_USER_USERNAME,
        "password": TEST_USER_PASSWORD,
    })

    # Login
    status, body, headers = req("POST", "/auth/login", {
        "username": TEST_USER_USERNAME,
        "password": TEST_USER_PASSWORD,
    })
    if status != 200:
        raise AssertionError(f"customer login failed with status {status}: {body}")
    if not isinstance(body, dict):
        raise AssertionError("customer login response is not JSON")

    cookie = hdr(headers, "Set-Cookie").split(";", 1)[0]
    csrf = str(body.get("csrf_token") or "")
    if not cookie:
        raise AssertionError("customer login did not return cookie")
    USER_SESSION_COOKIE = cookie
    USER_SESSION_CSRF = csrf
    return USER_SESSION_COOKIE, USER_SESSION_CSRF


def customer_auth_headers() -> dict[str, str]:
    """Headers for /api/generate endpoints: internal token + user cookie + CSRF."""
    if not API_AUTH_TOKEN:
        raise AssertionError("API_AUTH_TOKEN is missing from environment or backend/.env")
    u_cookie, u_csrf = customer_session()
    return {
        "X-API-Auth": API_AUTH_TOKEN,
        "Cookie": u_cookie,
        "X-CSRF-Token": u_csrf,
    }


print("=" * 60)
print(" SECURITY ACCEPTANCE TEST SUITE")
print("=" * 60)


print("\n--- Phase 1: Cookie Authentication ---")


def t_login():
    cookie, _ = session()
    check_in_text("access_token=", cookie)


test("1.1 login returns session cookie and CSRF token", t_login)


def t_me_authed():
    cookie, _ = session()
    status, body, _ = req("GET", "/admin/me", extra_headers={"Cookie": cookie})
    check(status, 200)
    if not isinstance(body, dict):
        raise AssertionError("me response is not JSON")
    check(body.get("username"), "admin")
    if not body.get("csrf_token"):
        raise AssertionError("me response did not include csrf_token")


test("1.2 GET /admin/me with cookie returns user", t_me_authed)


def t_me_unauth():
    status, _, _ = req("GET", "/admin/me")
    check(status, 401)


test("1.3 GET /admin/me 401 without cookie", t_me_unauth)


def t_logout_requires_csrf():
    cookie, _ = session()
    status, _, _ = req("POST", "/admin/logout", extra_headers={"Cookie": cookie})
    check(status, 403)


test("1.4 logout rejects missing CSRF token", t_logout_requires_csrf)


def t_keys_unauth():
    status, _, _ = req("GET", "/admin/api-keys")
    check(status, 401)


test("1.5 API keys require auth", t_keys_unauth)


print("\n--- Phase 2: API and CORS Contract ---")


def t_cors_allowed():
    status, _, headers = req("OPTIONS", "/admin/login", origin=EXPECTED_CORS_ORIGIN, cors_method="POST")
    check(status, 200)
    check(hdr(headers, "Access-Control-Allow-Origin"), EXPECTED_CORS_ORIGIN)


test(f"2.1 CORS allows {EXPECTED_CORS_ORIGIN}", t_cors_allowed)


def t_cors_blocked():
    status, _, headers = req("OPTIONS", "/admin/login", origin="https://evil.com", cors_method="POST")
    check(status, 400)
    check(hdr(headers, "Access-Control-Allow-Origin"), "")


test("2.2 CORS blocks evil origin", t_cors_blocked)


def t_generate_requires_internal_token():
    status, _, _ = req("POST", "/api/generate", {"image_url": "https://x.com/x.jpg"})
    # Empty API_AUTH_TOKEN → 503; configured but missing header → 403
    expected = 503 if not API_AUTH_TOKEN else 403
    check(status, expected)


test("2.3 /api/generate rejects missing internal API auth", t_generate_requires_internal_token)


def t_py_country():
    status, _, _ = req("POST", "/api/generate",
                       {"image_url": "https://x.com/x.jpg", "country": "INVALID"},
                       extra_headers=customer_auth_headers())
    check(status, 422)


test("2.4 invalid country -> 422", t_py_country)


def t_py_url_sync():
    status, _, _ = req("POST", "/api/generate",
                       {"image_url": "not-a-url"},
                       extra_headers=customer_auth_headers())
    check_in(status, [400, 422])


test("2.5 sync invalid image_url -> 4xx", t_py_url_sync)


def t_py_url_async():
    status, _, _ = req("POST", "/api/generate/async",
                       {"image_url": "not-a-url"},
                       extra_headers=customer_auth_headers())
    check_in(status, [400, 422])


test("2.6 async invalid image_url -> 4xx", t_py_url_async)


def t_key_update_missing():
    cookie, csrf = session()
    status, _, _ = req(
        "PUT",
        "/admin/api-keys/2147483647",
        {"name": "missing"},
        extra_headers={"Cookie": cookie, "X-CSRF-Token": csrf},
    )
    check(status, 404)


test("2.7 updating a missing API key returns 404", t_key_update_missing)


def t_key_delete_missing():
    cookie, csrf = session()
    status, _, _ = req(
        "DELETE",
        "/admin/api-keys/2147483647",
        extra_headers={"Cookie": cookie, "X-CSRF-Token": csrf},
    )
    check(status, 404)


test("2.8 deleting a missing API key returns 404", t_key_delete_missing)


def t_logout_with_csrf():
    global SESSION_COOKIE, SESSION_CSRF
    cookie, csrf = session()
    status, _, headers = req("POST", "/admin/logout", extra_headers={"Cookie": cookie, "X-CSRF-Token": csrf})
    check(status, 200)
    set_cookie = hdr(headers, "Set-Cookie")
    check_in_text("max-age=0", set_cookie)
    if COOKIE_SECURE:
        check_in_text("secure", set_cookie.lower())
    SESSION_COOKIE = ""
    SESSION_CSRF = ""


test("2.9 logout clears cookie with CSRF token", t_logout_with_csrf)


print("\n--- Phase 3: Defense in Depth ---")


def t_ratelimit():
    codes = []
    for _ in range(8):
        status, _, _ = req("POST", "/admin/login", {"username": "__missing_user__", "password": "__bad__"})
        codes.append(status)
    if 429 not in codes:
        raise AssertionError(f"expected at least one 429, got {codes}")


test("3.1 login rate-limited to 5/min", t_ratelimit)


def t_health():
    status, body, _ = req("GET", "/health")
    check(status, 200)
    if not isinstance(body, dict):
        raise AssertionError("health response is not JSON")
    check(body.get("status"), "ok")


test("3.2 health endpoint ok", t_health)


def t_project_files():
    check((ROOT / ".env.example").exists(), True)
    check((BACKEND_DIR / "requirements.txt").exists(), True)
    check((ROOT / "src" / "middleware.ts").exists(), True)


test("3.3 deployment/security support files exist", t_project_files)


print("\n" + "=" * 60)
total = PASS + FAIL
print(f"  TOTAL: {total}  |  PASS: {PASS}  |  FAIL: {FAIL}")
print("  **  ALL TESTS PASSED" if FAIL == 0 else "  !!  SOME TESTS FAILED")
print("=" * 60)
sys.exit(FAIL)
