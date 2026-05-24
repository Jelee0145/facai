"""Security Acceptance Test Suite — v2 (isolated, deterministic)"""
import json, os, sys, time, urllib.request, urllib.error

BASE = os.getenv("TEST_BASE", "http://localhost:8001")
PASS = 0
FAIL = 0

def test(name, fn):
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

def hdr(headers, key):
    """case-insensitive header lookup"""
    lower = key.lower()
    for k, v in headers.items():
        if k.lower() == lower:
            return v
    return ""

def req(method, path, body=None, extra_headers=None, origin=None, cors_method=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method)
    if data:
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
        ct = hdr(resp.headers, "Content-Type")
        bodyj = json.loads(raw) if "json" in ct else raw.decode()
        return resp.status, bodyj, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        ct = hdr(e.headers, "Content-Type")
        bodyj = json.loads(raw) if "json" in ct else raw.decode()
        return e.code, bodyj, dict(e.headers)
    except urllib.error.URLError as e:
        raise RuntimeError(f"Cannot reach {url}: {e.reason}")

def check(val, exp, msg=""):
    if val != exp:
        raise AssertionError(f"expected {exp!r}, got {val!r}. {msg}")

def check_in(val, col, msg=""):
    if val not in col:
        raise AssertionError(f"expected {val!r} in {col}. {msg}")

def check_in_text(val, text, msg=""):
    if val.lower() not in text.lower():
        raise AssertionError(f"expected '{val}' in '{text}'. {msg}")

print("=" * 60)
print(" SECURITY ACCEPTANCE TEST SUITE")
print("=" * 60)

# ---- Phase 1: Auth ----
print("\n--- Phase 1: Cookie Authentication ---")

def t_login():
    s, b, headers = req("POST", "/admin/login", {"username": "admin", "password": "admin123"})
    check(s, 200)
    cookie = hdr(headers, "Set-Cookie")
    check_in_text("access_token=", cookie)
    check_in_text("httponly", cookie)
    check_in_text("samesite=lax", cookie)
    check_in_text("path=/", cookie)
test("1.1 login returns Set-Cookie (HttpOnly/SameSite/Path)", t_login)

def t_me_authed():
    s, b, _ = req("POST", "/admin/login", {"username": "admin", "password": "admin123"})
    check(s, 200)
    # second request uses the same client — urllib doesn't auto-send cookies
    # so manually extract cookie
    _, _, h2 = req("POST", "/admin/login", {"username": "admin", "password": "admin123"})
    cookie = hdr(h2, "Set-Cookie").split(";")[0]
    s2, b2, _ = req("GET", "/admin/me", extra_headers={"Cookie": cookie})
    check(s2, 200)
    check(b2.get("username"), "admin")
test("1.2 GET /admin/me with cookie returns user", t_me_authed)

def t_me_unauth():
    s, b, _ = req("GET", "/admin/me")
    check(s, 401)
test("1.3 GET /admin/me 401 without cookie", t_me_unauth)

def t_logout():
    _, _, h2 = req("POST", "/admin/login", {"username": "admin", "password": "admin123"})
    cookie = hdr(h2, "Set-Cookie").split(";")[0]
    s, b, h3 = req("POST", "/admin/logout", extra_headers={"Cookie": cookie})
    check(s, 200)
    sc = hdr(h3, "Set-Cookie")
    check_in_text("max-age=0", sc)
test("1.4 logout clears cookie", t_logout)

def t_keys_unauth():
    s, b, _ = req("GET", "/admin/api-keys")
    check(s, 401)
test("1.5 API keys require auth", t_keys_unauth)

# ---- Phase 2: Fixes ----
print("\n--- Phase 2: Security Fixes ---")

def t_cors_restricted():
    s, b, headers = req("OPTIONS", "/admin/login", origin="http://localhost:5000", cors_method="POST")
    allow = hdr(headers, "Access-Control-Allow-Origin")
    check(allow, "http://localhost:5000")
test("2.1 CORS Allow-Origin = http://localhost:5000", t_cors_restricted)

def t_cors_blocked():
    s, b, headers = req("OPTIONS", "/admin/login", origin="https://evil.com", cors_method="POST")
    allow = hdr(headers, "Access-Control-Allow-Origin")
    check(allow, "")
test("2.2 CORS blocks evil origin", t_cors_blocked)

def t_py_country():
    s, b, _ = req("POST", "/api/generate", {"image_url": "https://x.com/x.jpg", "country": "INVALID"})
    check(s, 422)
test("2.3 invalid country -> 422", t_py_country)

def t_py_gtype():
    s, b, _ = req("POST", "/api/generate", {"image_url": "https://x.com/x.jpg", "generate_type": "INVALID"})
    check(s, 422)
test("2.4 invalid generate_type -> 422", t_py_gtype)

def t_py_size():
    s, b, _ = req("POST", "/api/generate", {"image_url": "https://x.com/x.jpg", "prompt_size": "INVALID"})
    check(s, 422)
test("2.5 invalid prompt_size -> 422", t_py_size)

def t_py_url():
    s, b, _ = req("POST", "/api/generate", {"image_url": "not-a-url"})
    check(s, 422)
test("2.6 invalid image_url -> 422", t_py_url)

def t_py_style():
    s, b, _ = req("POST", "/api/generate", {"image_url": "https://x.com/x.jpg", "style_index": 99})
    check(s, 422)
test("2.7 style_index out of range -> 422", t_py_style)

# ---- Phase 3: Defense ----
print("\n--- Phase 3: Defense in Depth ---")

def t_ratelimit():
    codes = []
    for i in range(8):
        s, b, _ = req("POST", "/admin/login", {"username": "x", "password": "x"})
        codes.append(s)
    n429 = sum(1 for c in codes if c == 429)
    check(n429 > 0, True, f"expected 429, got {codes}")
    print(f"    (rate limit: {n429}x 429 / {len(codes)} reqs)")
test("3.1 login rate-limited to 5/min", t_ratelimit)

def t_no_path_leak():
    s, b, _ = req("POST", "/api/generate", {"image_url": "https://x.com/x.jpg"})
    check_in(s, [422, 500, 503])
    if s != 422:
        for junk in ["data.db", "C:\\", "D:\\", "PROJECT_ROOT"]:
            if junk in json.dumps(b):
                raise AssertionError(f"leaked: {junk}")
test("3.2 no filesystem path leak in errors", t_no_path_leak)

# ---- Phase 4: Hardening ----
print("\n--- Phase 4: Production Hardening ---")

def t_env_example():
    check(os.path.exists(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.example")), True)
test("4.1 .env.example exists", t_env_example)

def t_health():
    s, b, _ = req("GET", "/health")
    check(s, 200)
    check(b.get("status"), "ok")
test("4.2 health endpoint ok", t_health)

def t_requirements():
    check(os.path.exists(os.path.join(os.path.dirname(__file__), "requirements.txt")), True)
test("4.3 requirements.txt exists", t_requirements)

def t_middleware():
    check(os.path.exists(os.path.join(os.path.dirname(os.path.dirname(__file__)), "src", "middleware.ts")), True)
test("4.4 src/middleware.ts exists", t_middleware)

# ---- Summary ----
print("\n" + "=" * 60)
total = PASS + FAIL
print(f"  TOTAL: {total}  |  PASS: {PASS}  |  FAIL: {FAIL}")
print("  **  ALL TESTS PASSED" if FAIL == 0 else "  !!  SOME TESTS FAILED")
print("=" * 60)
sys.exit(FAIL)
