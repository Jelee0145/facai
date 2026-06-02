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
