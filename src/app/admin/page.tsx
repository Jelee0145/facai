"use client";

import { useState, useEffect } from "react";
import { useAuth } from "./auth-context";
import { toast } from "@/components/ui/toast";
import { logger } from "@/lib/logger";

interface KeyHealth {
  id: number;
  name: string;
  today_used: number;
  daily_limit: number;
  fail_count: number;
  usage_pct: number;
  balance_usd: number;
  remaining_quota: number;
}

interface DashboardStats {
  active_keys: number;
  total_keys: number;
  today_generations: number;
  today_success_rate: number;
  today_avg_time: number;
  total_generations: number;
  keys_health?: { keys: KeyHealth[] };
}

export default function DashboardPage() {
  const { fetchWithAuth } = useAuth();
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingKeyId, setEditingKeyId] = useState<number | null>(null);
  const [balanceInput, setBalanceInput] = useState<string>('');

  const load = () => {
    setError(null);
    fetchWithAuth("/api/admin/dashboard")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<DashboardStats>;
      })
      .then(setStats)
      .catch((e) => {
        setError("加载失败");
        logger.error("Failed to load dashboard:", e);
      });
  };

  useEffect(() => { load(); }, [fetchWithAuth]);

  const handleUpdateBalance = (keyId: number) => {
    const key = stats?.keys_health?.keys.find(k => k.id === keyId);
    setEditingKeyId(keyId);
    setBalanceInput(key?.balance_usd?.toString() || '0');
  };

  const submitBalanceUpdate = async () => {
    if (editingKeyId === null) return;
    const balance = parseFloat(balanceInput);
    if (isNaN(balance) || balance < 0) {
      toast.warning('请输入有效的余额金额');
      return;
    }

    try {
      const url = `/api/admin/api-keys/${editingKeyId}`;
      const res = await fetchWithAuth(url, {
        method: 'PUT',
        body: JSON.stringify({ balance_usd: balance }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        logger.error('Balance update failed:', res.status, err);
        throw new Error(err.detail || '更新失败');
      }
      setEditingKeyId(null);
      load();
    } catch (e) {
      logger.error('Balance update error:', e);
      toast.error(`设置余额失败: ${e instanceof Error ? e.message : '未知错误'}`);
    }
  };

  const cancelBalanceUpdate = () => {
    setEditingKeyId(null);
    setBalanceInput('');
  };

  if (error) return (
    <div className="text-red-400 bg-red-900/30 border border-red-800 rounded-xl p-4">
      加载失败，请检查网络连接
      <button onClick={load} className="ml-3 underline hover:text-red-300">重试</button>
    </div>
  );

  if (!stats) return <div className="text-gray-400">加载中...</div>;

  const cards = [
    { label: "活跃 Keys", value: `${stats.active_keys}/${stats.total_keys}`, color: "from-green-500 to-emerald-500" },
    { label: "今日生成", value: stats.today_generations, color: "from-purple-500 to-pink-500" },
    { label: "成功率", value: `${stats.today_success_rate}%`, color: "from-blue-500 to-cyan-500" },
    { label: "平均耗时", value: `${stats.today_avg_time}s`, color: "from-orange-500 to-yellow-500" },
    { label: "总生成数", value: stats.total_generations, color: "from-red-500 to-rose-500" },
  ];

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">📊 仪表盘</h1>

      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4 mb-8">
        {cards.map((card) => (
          <div key={card.label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <div className="text-sm text-gray-400 mb-1">{card.label}</div>
            <div className={`text-2xl font-bold bg-gradient-to-r ${card.color} bg-clip-text text-transparent`}>
              {card.value}
            </div>
          </div>
        ))}
      </div>

      <h2 className="text-lg font-semibold mb-4">🔑 Key 使用状态</h2>
      <div className="space-y-3">
        {(stats.keys_health?.keys || []).map((k: KeyHealth) => (
          <div key={k.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium">{k.name}</span>
              <span className={`text-xs px-2 py-1 rounded ${k.fail_count > 0 ? "bg-red-900/50 text-red-400" : "bg-green-900/50 text-green-400"}`}>
                {k.fail_count > 0 ? `${k.fail_count} 次失败` : "正常"}
              </span>
            </div>
            {k.balance_usd > 0 ? (
              <div className="flex justify-between text-xs text-gray-400 mt-2">
                <span>
                  剩余 <span className="text-purple-400 font-semibold">{k.remaining_quota || 0}</span> 张
                  <span className="text-gray-500 ml-2">${(k.balance_usd || 0).toFixed(2)}</span>
                </span>
              </div>
            ) : (
              <>
                <div className="w-full bg-gray-800 rounded-full h-2 mt-2">
                  <div
                    className={`h-2 rounded-full transition-all ${k.usage_pct > 80 ? "bg-red-500" : "bg-purple-500"}`}
                    style={{ width: `${Math.min(k.usage_pct, 100)}%` }}
                  />
                </div>
                <div className="flex justify-between text-xs text-gray-500 mt-1">
                  <span>{k.today_used} / {k.daily_limit}</span>
                  <span>{k.usage_pct}%</span>
                </div>
              </>
            )}

            {/* Balance Information */}
            <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-800">
              {editingKeyId === k.id ? (
                <div className="flex items-center gap-2 flex-1">
                  <span className="text-gray-400">$</span>
                  <input
                    type="number"
                    value={balanceInput}
                    onChange={(e) => setBalanceInput(e.target.value)}
                    className="w-24 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-purple-500"
                    min="0"
                    step="0.01"
                    autoFocus
                  />
                  <span className="text-gray-500 text-xs">
                    = {Math.floor(parseFloat(balanceInput) / 0.006) || 0} 张
                  </span>
                  <button
                    onClick={submitBalanceUpdate}
                    className="text-xs px-2 py-1 bg-green-600 hover:bg-green-500 rounded text-white"
                  >
                    确认
                  </button>
                  <button
                    onClick={cancelBalanceUpdate}
                    className="text-xs px-2 py-1 bg-gray-700 hover:bg-gray-600 rounded text-white"
                  >
                    取消
                  </button>
                </div>
              ) : (
                <>
                  <div className="text-sm text-gray-400">
                    <span className="text-green-400 font-semibold">
                      ${(k.balance_usd || 0).toFixed(2)}
                    </span>
                    <span className="text-gray-500 ml-2">
                      剩余 <span className="text-purple-400 font-semibold">
                        {k.remaining_quota || 0}
                      </span> 张
                    </span>
                  </div>
                  <button
                    onClick={() => handleUpdateBalance(k.id)}
                    className="text-xs px-2 py-1 bg-gray-800 hover:bg-gray-700 rounded"
                  >
                    设置余额
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
        {(!stats.keys_health?.keys || stats.keys_health.keys.length === 0) && (
          <div className="text-gray-500 text-center py-4">暂无活跃 Key</div>
        )}
      </div>
    </div>
  );
}
