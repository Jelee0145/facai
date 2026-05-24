"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useState, useEffect } from "react";
import { useAuth } from "./auth-context";

export default function DashboardPage() {
  const { fetchWithAuth } = useAuth();
  const [stats, setStats] = useState<any>(null);

  useEffect(() => {
    fetchWithAuth("/api/admin/dashboard")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setStats)
      .catch(() => {});
  }, [fetchWithAuth]);

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
        {(stats.keys_health?.keys || []).map((k: any) => (
          <div key={k.id} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="font-medium">{k.name}</span>
              <span className={`text-xs px-2 py-1 rounded ${k.fail_count > 0 ? "bg-red-900/50 text-red-400" : "bg-green-900/50 text-green-400"}`}>
                {k.fail_count > 0 ? `${k.fail_count} 次失败` : "正常"}
              </span>
            </div>
            <div className="w-full bg-gray-800 rounded-full h-2">
              <div
                className={`h-2 rounded-full transition-all ${k.usage_pct > 80 ? "bg-red-500" : "bg-purple-500"}`}
                style={{ width: `${Math.min(k.usage_pct, 100)}%` }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>{k.today_used} / {k.daily_limit}</span>
              <span>{k.usage_pct}%</span>
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
