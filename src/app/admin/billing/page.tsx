"use client";

import { useEffect, useState } from "react";
import { useAuth } from "../auth-context";
import { toast } from "@/components/ui/toast";
import { logger } from "@/lib/logger";

interface CreditPackage {
  id: number;
  name: string;
  price_fen: number;
  points: number;
  bonus_points: number;
  status: "active" | "inactive";
  sort_order: number;
}

interface OrderItem {
  id: number;
  order_no: string;
  username?: string;
  package_name?: string;
  amount_fen: number;
  points: number;
  status: string;
  created_at: string;
}

const emptyPackage: Omit<CreditPackage, "id"> = {
  name: "",
  price_fen: 0,
  points: 100,
  bonus_points: 0,
  status: "active",
  sort_order: 100,
};

export default function BillingPage() {
  const { fetchWithAuth } = useAuth();
  const [packages, setPackages] = useState<CreditPackage[]>([]);
  const [orders, setOrders] = useState<OrderItem[]>([]);
  const [generationCostPoints, setGenerationCostPoints] = useState(10);
  const [newPackage, setNewPackage] = useState(emptyPackage);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([
      fetchWithAuth("/api/admin/credit-packages").then((r) => r.json()),
      fetchWithAuth("/api/admin/orders").then((r) => r.json()),
    ])
      .then(([packageData, orderData]) => {
        setPackages(packageData.packages || []);
        setGenerationCostPoints(packageData.generation_cost_points || 10);
        setOrders(orderData.orders || []);
      })
      .catch((e) => {
        toast.error("计费数据加载失败");
        logger.error("Failed to load billing admin data:", e);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  const saveCost = async () => {
    setMutating(true);
    try {
      const r = await fetchWithAuth("/api/admin/generation-cost", {
        method: "PUT",
        body: JSON.stringify({ points: generationCostPoints }),
      });
      if (!r.ok) {
        toast.error("扣费配置保存失败");
        return;
      }
      toast.success("扣费配置已保存");
    } finally {
      setMutating(false);
    }
  };

  const addPackage = async () => {
    if (!newPackage.name.trim()) {
      toast.warning("请输入套餐名称");
      return;
    }
    setMutating(true);
    try {
      const r = await fetchWithAuth("/api/admin/credit-packages", {
        method: "POST",
        body: JSON.stringify(newPackage),
      });
      if (!r.ok) {
        toast.error("套餐保存失败");
        return;
      }
      setNewPackage(emptyPackage);
      load();
    } finally {
      setMutating(false);
    }
  };

  const togglePackage = async (pkg: CreditPackage) => {
    setMutating(true);
    try {
      const r = await fetchWithAuth(`/api/admin/credit-packages/${pkg.id}`, {
        method: "PUT",
        body: JSON.stringify({ ...pkg, status: pkg.status === "active" ? "inactive" : "active" }),
      });
      if (!r.ok) {
        toast.error("套餐状态更新失败");
        return;
      }
      load();
    } finally {
      setMutating(false);
    }
  };

  const markPaid = async (orderNo: string) => {
    setMutating(true);
    try {
      const r = await fetchWithAuth(`/api/admin/orders/${orderNo}/mark-paid`, { method: "POST" });
      if (!r.ok) {
        toast.error("订单入账失败");
        return;
      }
      toast.success("订单已入账");
      load();
    } finally {
      setMutating(false);
    }
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">计费管理</h1>
        {loading && <span className="text-sm text-gray-500">加载中...</span>}
      </div>

      <section className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-4">生成扣费</h2>
        <div className="flex gap-3">
          <input
            type="number"
            min={1}
            value={generationCostPoints}
            onChange={(e) => {
              const v = parseInt(e.target.value);
              setGenerationCostPoints(Number.isNaN(v) ? 1 : Math.max(1, v));
            }}
            className="w-40 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white"
          />
          <button onClick={saveCost} disabled={mutating} className="px-4 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 rounded-lg text-sm">
            保存每次扣费积分
          </button>
        </div>
      </section>

      <section className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-4">积分套餐</h2>
        <div className="grid grid-cols-1 md:grid-cols-6 gap-3 mb-4">
          <input value={newPackage.name} onChange={(e) => setNewPackage({ ...newPackage, name: e.target.value })} placeholder="套餐名" className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white" />
          <input type="number" value={newPackage.price_fen} onChange={(e) => setNewPackage({ ...newPackage, price_fen: parseInt(e.target.value) || 0 })} placeholder="价格分" className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white" />
          <input type="number" value={newPackage.points} onChange={(e) => setNewPackage({ ...newPackage, points: parseInt(e.target.value) || 1 })} placeholder="积分" className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white" />
          <input type="number" value={newPackage.bonus_points} onChange={(e) => setNewPackage({ ...newPackage, bonus_points: parseInt(e.target.value) || 0 })} placeholder="赠送" className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white" />
          <input type="number" value={newPackage.sort_order} onChange={(e) => setNewPackage({ ...newPackage, sort_order: parseInt(e.target.value) || 100 })} placeholder="排序" className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white" />
          <button onClick={addPackage} disabled={mutating} className="px-4 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 rounded-lg text-sm">新增套餐</button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {packages.map((pkg) => (
            <div key={pkg.id} className="border border-gray-800 rounded-lg p-4">
              <div className="font-semibold">{pkg.name}</div>
              <div className="text-gray-400 text-sm mt-1">¥{(pkg.price_fen / 100).toFixed(2)} · {pkg.points + pkg.bonus_points} 积分</div>
              <button onClick={() => togglePackage(pkg)} disabled={mutating} className="mt-3 px-3 py-1 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded text-xs">
                {pkg.status === "active" ? "停用" : "启用"}
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="p-4 font-semibold">充值订单</div>
        <table className="w-full text-sm">
          <thead className="bg-gray-800/50 text-gray-400">
            <tr>
              <th className="px-4 py-3 text-left">订单号</th>
              <th className="px-4 py-3 text-left">用户</th>
              <th className="px-4 py-3 text-left">套餐</th>
              <th className="px-4 py-3 text-left">金额</th>
              <th className="px-4 py-3 text-left">积分</th>
              <th className="px-4 py-3 text-left">状态</th>
              <th className="px-4 py-3 text-left">操作</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => (
              <tr key={order.id} className="border-t border-gray-800">
                <td className="px-4 py-3 font-mono text-xs">{order.order_no}</td>
                <td className="px-4 py-3">{order.username || "-"}</td>
                <td className="px-4 py-3">{order.package_name || "-"}</td>
                <td className="px-4 py-3">¥{(order.amount_fen / 100).toFixed(2)}</td>
                <td className="px-4 py-3">{order.points}</td>
                <td className="px-4 py-3">{order.status}</td>
                <td className="px-4 py-3">
                  {order.status !== "credited" && (
                    <button onClick={() => markPaid(order.order_no)} disabled={mutating} className="px-3 py-1 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 rounded text-xs">
                      标记支付并入账
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {orders.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-gray-500">暂无订单</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
