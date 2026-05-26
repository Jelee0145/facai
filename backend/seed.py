"""将 .env 中的 API Key 导入数据库并创建管理员"""
import os
import secrets
from dotenv import load_dotenv

load_dotenv()

from database import init_db, get_key_by_value, add_key, get_config, set_config
from security import hash_password
from database import create_user, get_user

init_db()

# 创建管理员
if not get_user("admin"):
    seed_password = os.getenv("ADMIN_PASSWORD", "") or secrets.token_urlsafe(12)
    create_user("admin", hash_password(seed_password))
    print("[SEED] Admin account created")
    print("[SEED] Username: admin")
    if not os.getenv("ADMIN_PASSWORD"):
        env_path = os.path.join(os.path.dirname(__file__) or ".", ".env")
        try:
            with open(env_path, "a" if os.path.exists(env_path) else "w", encoding="utf-8") as f:
                f.write(f"\nADMIN_PASSWORD={seed_password}\n")
            print("[SEED] Password saved to backend/.env (ADMIN_PASSWORD)")
        except Exception:
            print("[SEED] WARNING: Could not save password to .env")
    else:
        print("[SEED] Password set from ADMIN_PASSWORD environment variable")
else:
    print("[SEED] 管理员账号已存在")

# 导入 API Key
api_key = os.getenv("APIMART_API_KEY", "")
if api_key and not get_key_by_value(api_key):
    add_key(api_key, name="默认 Key", daily_limit=200)
    print(f"[SEED] API Key 已导入: {api_key[:15]}...")
else:
    print("[SEED] API Key 已存在或为空")

# 导入 LLM 默认配置（仅当 system_config 中尚无配置时）
llm_api_key = os.getenv("LLM_API_KEY", "")
if llm_api_key and not get_config("llm_api_key"):
    set_config("llm_api_key", llm_api_key)
    print(f"[SEED] LLM API Key 已导入")
else:
    print("[SEED] LLM API Key 已存在或为空")

llm_model = os.getenv("LLM_MODEL", "qwen3-vl-flash")
if llm_model and not get_config("llm_model"):
    set_config("llm_model", llm_model)
    print(f"[SEED] LLM Model 已设置: {llm_model}")
else:
    print("[SEED] LLM Model 已存在或未配置")
