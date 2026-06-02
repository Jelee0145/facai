"""将 .env 中的 API Key 导入数据库并创建/修复管理员"""
import os
import sys
import secrets
from dotenv import load_dotenv

load_dotenv()

from database import init_db, get_config, set_config, get_user, create_user, update_admin_password
from security import hash_password, is_valid_password_hash

init_db()

# ========== 管理员账号 ==========
WEAK_PASSWORDS = {"admin123", "password", "123456", "admin", "admin888", "test123"}
_is_production = os.getenv("NODE_ENV", "").lower() in ("production", "prod")
_admin = get_user("admin")
_admin_pw = os.getenv("ADMIN_PASSWORD", "")
_weak = _admin_pw.lower() in WEAK_PASSWORDS if _admin_pw else False

if not _admin:
    # Admin does not exist
    if _is_production and (not _admin_pw or _weak):
        print("[SEED] CRITICAL: Production requires a strong ADMIN_PASSWORD to create admin!")
        sys.exit(1)
    if not _admin_pw:
        # Dev: generate random password
        seed_password = secrets.token_urlsafe(16)
        create_user("admin", hash_password(seed_password))
        print("=" * 60)
        print(f"[SEED] Admin account created with AUTO-GENERATED password:")
        print(f"  Username : admin")
        print(f"  Password : {seed_password}")
        print(f"[SEED] Please save this password! It will NOT be shown again.")
        print(f"[SEED] You can also set ADMIN_PASSWORD in .env and restart.")
        print("=" * 60)
    else:
        create_user("admin", hash_password(_admin_pw))
        print("[SEED] Admin account created from ADMIN_PASSWORD")
elif not is_valid_password_hash(_admin.get("password_hash", "")):
    # Admin exists but hash is invalid — repair
    if _admin_pw and not _weak:
        update_admin_password("admin", hash_password(_admin_pw))
        print("[SEED] Admin password_hash was invalid — repaired from ADMIN_PASSWORD")
    else:
        msg = "[SEED] CRITICAL: Admin password_hash is invalid and no strong ADMIN_PASSWORD is available!"
        if _is_production:
            print(msg)
            sys.exit(1)
        else:
            print(msg)
else:
    print("[SEED] 管理员账号已存在")

# ========== 导入 LLM 默认配置 ==========
llm_api_key = os.getenv("LLM_API_KEY", "")
if llm_api_key and not get_config("llm_api_key"):
    set_config("llm_api_key", llm_api_key)
    print("[SEED] LLM API Key 已导入")
else:
    print("[SEED] LLM API Key 已存在或为空")

llm_model = os.getenv("LLM_MODEL", "qwen3-vl-flash")
if llm_model and not get_config("llm_model"):
    set_config("llm_model", llm_model)
    print(f"[SEED] LLM Model 已设置: {llm_model}")
else:
    print("[SEED] LLM Model 已存在或未配置")
