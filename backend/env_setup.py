"""自动填充 .env 文件中留空的关键密钥"""
import os
import secrets

_KEYS = {
    "JWT_SECRET": lambda: secrets.token_hex(32),
    "API_AUTH_TOKEN": lambda: secrets.token_hex(32),
    "ADMIN_PASSWORD": lambda: secrets.token_urlsafe(16),
}


def auto_fill_env(env_path=None):
    """Scan .env for blank key values and fill them with random ones.

    Only modifies keys listed in _KEYS that appear as "KEY=" (empty value).
    Existing non-empty values are never overwritten.
    If .env doesn't exist the function returns silently.
    """
    if env_path is None:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

    if not os.path.isfile(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    modified = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for key, gen in _KEYS.items():
            if stripped.startswith(key + "="):
                value = stripped[len(key) + 1:]
                if value == "":
                    new_value = gen()
                    lines[i] = f"{key}={new_value}\n"
                    print(f"[INIT] Auto-generated {key} in .env")
                    modified = True
                break

    if modified:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    # Always sync root .env — even when backend/.env was not modified this run,
    # the root .env may have a stale or mismatched token from a prior run.
    _sync_root_env(env_path)


def _sync_root_env(backend_env_path: str):
    """Copy the auto-filled API_AUTH_TOKEN to the root .env so the
    frontend Docker container can pick it up."""
    backend_dir = os.path.dirname(backend_env_path)
    root_env_path = os.path.normpath(os.path.join(backend_dir, "..", ".env"))

    # Read the token from the backend .env we just wrote
    token = None
    with open(backend_env_path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("API_AUTH_TOKEN="):
                token = stripped[len("API_AUTH_TOKEN="):]
                break
    if not token:
        return

    # Root .env doesn't exist yet — create it
    if not os.path.isfile(root_env_path):
        with open(root_env_path, "w", encoding="utf-8") as f:
            f.write(f"API_AUTH_TOKEN={token}\n")
        print("[INIT] Created root .env with API_AUTH_TOKEN")
        return

    # Update existing root .env — overwrite if token differs (backend/.env is source of truth)
    with open(root_env_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    found = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("API_AUTH_TOKEN="):
            old_val = stripped[len("API_AUTH_TOKEN="):]
            if old_val != token:
                lines[i] = f"API_AUTH_TOKEN={token}\n"
                print("[INIT] Synced API_AUTH_TOKEN to root .env (overwrote stale value)")
            found = True
            break

    if not found:
        lines.append(f"API_AUTH_TOKEN={token}\n")
        print("[INIT] Added API_AUTH_TOKEN to root .env")

    with open(root_env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
