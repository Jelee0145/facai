"use client";

import { useState, useEffect } from "react";
import { useAuth } from "../auth-context";
import { toast } from "@/components/ui/toast";
import { logger } from "@/lib/logger";

interface ApiKey {
  id: number;
  key_value: string;
  name: string;
  is_active: boolean;
  today_used: number;
  daily_limit: number;
  fail_count: number;
}

export default function KeysPage() {
  const { fetchWithAuth } = useAuth();
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [newKey, setNewKey] = useState({ key_value: "", name: "", daily_limit: 200 });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchWithAuth("/api/admin/api-keys")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<{ keys: ApiKey[] }>;
      })
      .then((d) => setKeys(d.keys || []))
      .catch((e) => {
        setError("加载失败");
        logger.error("Failed to load API keys:", e);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const addKey = async () => {
    if (!newKey.key_value.trim()) { toast.warning("Key 值不能为空"); return; }
    try {
      const r = await fetchWithAuth("/api/admin/api-keys", { method: "POST", body: JSON.stringify(newKey) });
      if (!r.ok) {
        const err: Record<string, unknown> = await r.json().catch(() => ({}));
        toast.error(String(err.detail || "添加失败"));
        return;
      }
      setNewKey({ key_value: "", name: "", daily_limit: 200 });
      setShowAdd(false);
      load();
    } catch {
      toast.error("网络错误");
    }
  };

  const toggleKey = async (id: number, isActive: boolean) => {
    const r = await fetchWithAuth(`/api/admin/api-keys/${id}`, { method: "PUT", body: JSON.stringify({ is_active: isActive ? 0 : 1 }) });
    if (!r.ok) {
      toast.error("Key 状态更新失败");
      return;
    }
    load();
  };

  const deleteKey = async (id: number) => {
    if (!confirm("确定删除此 Key？")) return;
    const r = await fetchWithAuth(`/api/admin/api-keys/${id}`, { method: "DELETE" });
    if (!r.ok) {
      toast.error("Key 删除失败");
      return;
    }
    load();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">🔑 API Keys 管理</h1>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-medium"
        >
          + 添加 Key
        </button>
      </div>

      {showAdd && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6 space-y-3">
          <input
            type="text" placeholder="API Key 值" value={newKey.key_value}
            onChange={(e) => setNewKey({ ...newKey, key_value: e.target.value })}
            className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
          />
          <div className="flex gap-3">
            <input
              type="text" placeholder="备注名称" value={newKey.name}
              onChange={(e) => setNewKey({ ...newKey, name: e.target.value })}
              className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
            />
            <input
              type="number" placeholder="每日限额" value={newKey.daily_limit}
              onChange={(e) => setNewKey({ ...newKey, daily_limit: parseInt(e.target.value) || 200 })}
              className="w-24 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
              min={1} max={1000}
            />
          </div>
          <div className="flex gap-2">
            <button onClick={addKey} className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-sm">保存</button>
            <button onClick={() => setShowAdd(false)} className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm">取消</button>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 mb-6 text-red-400">
          加载失败，请检查网络连接
          <button onClick={load} className="ml-3 underline hover:text-red-300">重试</button>
        </div>
      )}

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800/50">
            <tr className="text-left text-gray-400">
              <th className="px-4 py-3">名称</th>
              <th className="px-4 py-3">Key</th>
              <th className="px-4 py-3">状态</th>
              <th className="px-4 py-3">用量</th>
              <th className="px-4 py-3">失败</th>
              <th className="px-4 py-3">操作</th>
            </tr>
          </thead>
          <tbody>
            {keys.map((k) => (
              <tr key={k.id} className="border-t border-gray-800">
                <td className="px-4 py-3 font-medium">{k.name || "-"}</td>
                <td className="px-4 py-3 text-gray-400 font-mono text-xs">{k.key_value.slice(0, 12)}...</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded text-xs ${k.is_active ? "bg-green-900/50 text-green-400" : "bg-red-900/50 text-red-400"}`}>
                    {k.is_active ? "启用" : "禁用"}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400">{k.today_used}/{k.daily_limit}</td>
                <td className="px-4 py-3">
                  {k.fail_count > 0 ? <span className="text-red-400">{k.fail_count}</span> : <span className="text-gray-500">0</span>}
                </td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <button onClick={() => toggleKey(k.id, k.is_active)} className="text-xs px-2 py-1 rounded bg-gray-800 hover:bg-gray-700">
                      {k.is_active ? "禁用" : "启用"}
                    </button>
                    <button onClick={() => deleteKey(k.id)} className="text-xs px-2 py-1 rounded bg-red-900/30 hover:bg-red-900/50 text-red-400">
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {loading && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">加载中...</td></tr>
            )}
            {!loading && keys.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-gray-500">暂无 API Key</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
