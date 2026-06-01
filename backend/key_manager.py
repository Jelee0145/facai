"""
API Key 负载均衡管理器
支持多 Key 轮询、故障自动禁用、每日限额管理
"""

import threading
from typing import Optional
from database import get_active_keys, mark_key_used, mark_key_failed, get_key_by_value


class KeyManager:
    """多 API Key 轮询 + 故障转移"""

    def __init__(self):
        self._lock = threading.Lock()
        self._current_index = -1

    def get_active_key(self) -> Optional[dict]:
        """获取下一个可用 Key（轮询）"""
        with self._lock:
            keys = get_active_keys()
            if not keys:
                return None

            self._current_index = (self._current_index + 1) % len(keys)
            return keys[self._current_index]

    def mark_success(self, key_value: str):
        """标记成功（原子递增，超限时忽略）"""
        row = get_key_by_value(key_value)
        if row:
            ok = mark_key_used(row["id"])
            if not ok:
                print(f"[WARN] Key {row['id']} 已达每日限额")

    def mark_failure(self, key_value: str):
        """标记失败"""
        row = get_key_by_value(key_value)
        if row:
            mark_key_failed(row["id"])

    def health_check(self) -> dict:
        """Key 健康状态概览"""
        keys = get_active_keys()
        total = len(keys)
        available = sum(1 for k in keys if k["fail_count"] == 0)
        return {
            "total_active": total,
            "healthy": available,
            "degraded": total - available,
            "keys": [
                {
                    "id": k["id"],
                    "name": k["name"],
                    "today_used": k["today_used"],
                    "daily_limit": k["daily_limit"],
                    "fail_count": k["fail_count"],
                    "usage_pct": round(k["today_used"] / k["daily_limit"] * 100, 1) if k["daily_limit"] else 0,
                    "balance_usd": k.get("balance_usd", 0) or 0,
                    "remaining_quota": int((k.get("balance_usd", 0) or 0) / 0.006),
                }
                for k in keys
            ],
        }


# 全局单例
key_manager = KeyManager()
