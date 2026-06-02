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
  payment_remark?: string;
  proof_image?: string;
  submitted_at?: string;
  reviewed_at?: string;
  reviewer_note?: string;
  reject_reason?: string;
  created_at: string;
}

interface PackageForm {
  name: string;
  price_fen: string;
  points: string;
  bonus_points: string;
  sort_order: string;
}

const emptyForm: PackageForm = {
  name: "",
  price_fen: "",
  points: "",
  bonus_points: "",
  sort_order: "",
};

const STATUS_MAP: Record<string, { label: string; bg: string; text: string }> = {
  pending: { label: "待支付", bg: "bg-blue-900/60", text: "text-blue-300" },
  submitted: { label: "待审核", bg: "bg-yellow-900/60", text: "text-yellow-300" },
  paid: { label: "已支付", bg: "bg-green-900/60", text: "text-green-300" },
  credited: { label: "已入账", bg: "bg-green-900/60", text: "text-green-300" },
  rejected: { label: "已驳回", bg: "bg-red-900/60", text: "text-red-300" },
};

const proofUrl = (path: string) => `/api/proof-image?path=${encodeURIComponent(path)}`;

export default function BillingPage() {
  const { fetchWithAuth } = useAuth();
  const [packages, setPackages] = useState<CreditPackage[]>([]);
  const [orders, setOrders] = useState<OrderItem[]>([]);
  const [generationCostPoints, setGenerationCostPoints] = useState(10);
  const [form, setForm] = useState<PackageForm>(emptyForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [rejectTarget, setRejectTarget] = useState<OrderItem | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [reviewerNote, setReviewerNote] = useState("");
  const [previewImage, setPreviewImage] = useState<string | null>(null);

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

  const startEdit = (pkg: CreditPackage) => {
    setEditingId(pkg.id);
    setForm({
      name: pkg.name,
      price_fen: String(pkg.price_fen),
      points: String(pkg.points),
      bonus_points: String(pkg.bonus_points),
      sort_order: String(pkg.sort_order),
    });
  };

  const cancelEdit = () => {
    setEditingId(null);
    setForm(emptyForm);
  };

  const submitForm = async () => {
    if (!form.name.trim()) {
      toast.warning("请输入套餐名称");
      return;
    }
    if (!form.price_fen || !form.points) {
      toast.warning("请填写价格和积分");
      return;
    }

    const body = {
      name: form.name.trim(),
      price_fen: parseInt(form.price_fen) || 0,
      points: parseInt(form.points) || 0,
      bonus_points: parseInt(form.bonus_points) || 0,
      status: "active",
      sort_order: parseInt(form.sort_order) || 100,
    };

    setMutating(true);
    try {
      const url = editingId
        ? `/api/admin/credit-packages/${editingId}`
        : "/api/admin/credit-packages";
      const method = editingId ? "PUT" : "POST";
      const r = await fetchWithAuth(url, { method, body: JSON.stringify(body) });
      if (!r.ok) {
        toast.error(editingId ? "套餐更新失败" : "套餐创建失败");
        return;
      }
      toast.success(editingId ? "套餐已更新" : "套餐已创建");
      cancelEdit();
      load();
    } finally {
      setMutating(false);
    }
  };

  const deletePackage = async (pkg: CreditPackage) => {
    if (!window.confirm(`确定删除套餐「${pkg.name}」吗？此操作不可撤销。`)) return;
    setMutating(true);
    try {
      const r = await fetchWithAuth(`/api/admin/credit-packages/${pkg.id}`, {
        method: "DELETE",
      });
      if (!r.ok) {
        if (r.status === 409) {
          toast.error("该套餐已有关联订单，无法删除。可改为停用。");
        } else {
          toast.error("删除失败");
        }
        return;
      }
      toast.success("套餐已删除");
      if (editingId === pkg.id) cancelEdit();
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
      const r = await fetchWithAuth(`/api/admin/orders/${orderNo}/mark-paid`, {
        method: "POST",
        body: JSON.stringify({ reviewer_note: reviewerNote }),
      });
      if (!r.ok) {
        toast.error("订单入账失败");
        return;
      }
      toast.success("订单已入账");
      setReviewerNote("");
      load();
    } finally {
      setMutating(false);
    }
  };

  const rejectOrder = async () => {
    if (!rejectTarget || !rejectReason.trim()) return;
    setMutating(true);
    try {
      const r = await fetchWithAuth(`/api/admin/orders/${rejectTarget.order_no}/reject`, {
        method: "POST",
        body: JSON.stringify({ reject_reason: rejectReason.trim() }),
      });
      if (!r.ok) {
        const data = await r.json().catch(() => ({}));
        toast.error(String(data.detail || "驳回失败"));
        return;
      }
      toast.success("订单已驳回");
      setRejectTarget(null);
      setRejectReason("");
      load();
    } finally {
      setMutating(false);
    }
  };

  const filteredOrders = statusFilter === "all"
    ? orders
    : orders.filter((o) => o.status === statusFilter);

  // Sort: submitted first, then by created_at desc
  const sortedOrders = [...filteredOrders].sort((a, b) => {
    const priority: Record<string, number> = { submitted: 0, pending: 1, rejected: 2, paid: 3, credited: 4 };
    const pa = priority[a.status] ?? 5;
    const pb = priority[b.status] ?? 5;
    if (pa !== pb) return pa - pb;
    return b.created_at.localeCompare(a.created_at);
  });

  const submittedCount = orders.filter((o) => o.status === "submitted").length;

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">计费管理</h1>
        {loading && <span className="text-sm text-gray-500">加载中...</span>}
      </div>

      {/* 生成扣费 */}
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

      {/* 积分套餐 */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-4">
          积分套餐
          {editingId !== null && (
            <span className="ml-2 text-sm font-normal text-yellow-400">
              编辑模式
            </span>
          )}
        </h2>

        {/* 表单 */}
        <div className="grid grid-cols-1 md:grid-cols-6 gap-3 mb-4">
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="套餐名称，如：体验包"
            className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder:text-gray-500"
          />
          <input
            type="number"
            min={0}
            value={form.price_fen}
            onChange={(e) => setForm({ ...form, price_fen: e.target.value })}
            placeholder="价格（分），如 990"
            className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder:text-gray-500"
          />
          <input
            type="number"
            min={1}
            value={form.points}
            onChange={(e) => setForm({ ...form, points: e.target.value })}
            placeholder="基础积分数量"
            className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder:text-gray-500"
          />
          <input
            type="number"
            min={0}
            value={form.bonus_points}
            onChange={(e) => setForm({ ...form, bonus_points: e.target.value })}
            placeholder="赠送积分数量"
            className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder:text-gray-500"
          />
          <input
            type="number"
            min={0}
            value={form.sort_order}
            onChange={(e) => setForm({ ...form, sort_order: e.target.value })}
            placeholder="排序权重，越小越靠前"
            className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder:text-gray-500"
          />
          <div className="flex gap-2">
            <button
              onClick={submitForm}
              disabled={mutating}
              className={`flex-1 px-4 py-2 disabled:opacity-50 rounded-lg text-sm ${
                editingId !== null
                  ? "bg-yellow-600 hover:bg-yellow-700"
                  : "bg-green-600 hover:bg-green-700"
              }`}
            >
              {editingId !== null ? "保存修改" : "新增套餐"}
            </button>
            {editingId !== null && (
              <button
                onClick={cancelEdit}
                disabled={mutating}
                className="px-3 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 rounded-lg text-sm"
              >
                取消
              </button>
            )}
          </div>
        </div>

        {/* 套餐卡片 */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {packages.map((pkg) => (
            <div
              key={pkg.id}
              className={`border rounded-lg p-4 ${
                editingId === pkg.id
                  ? "border-yellow-500 bg-gray-800/50"
                  : "border-gray-800"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold">{pkg.name}</span>
                <span
                  className={`text-xs px-2 py-0.5 rounded ${
                    pkg.status === "active"
                      ? "bg-green-900 text-green-300"
                      : "bg-gray-700 text-gray-400"
                  }`}
                >
                  {pkg.status === "active" ? "启用" : "停用"}
                </span>
              </div>
              <div className="text-gray-400 text-sm mt-2 space-y-0.5">
                <div>价格：¥{(pkg.price_fen / 100).toFixed(2)}</div>
                <div>
                  积分：{pkg.points} 基础
                  {pkg.bonus_points > 0 && ` + ${pkg.bonus_points} 赠送`}
                  {" = "}
                  <span className="text-white">{pkg.points + pkg.bonus_points}</span>
                </div>
                <div>排序：{pkg.sort_order}</div>
              </div>
              <div className="flex gap-2 mt-3">
                <button
                  onClick={() => startEdit(pkg)}
                  disabled={mutating}
                  className="px-3 py-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 rounded text-xs"
                >
                  编辑
                </button>
                <button
                  onClick={() => togglePackage(pkg)}
                  disabled={mutating}
                  className="px-3 py-1 bg-gray-800 hover:bg-gray-700 disabled:opacity-50 rounded text-xs"
                >
                  {pkg.status === "active" ? "停用" : "启用"}
                </button>
                <button
                  onClick={() => deletePackage(pkg)}
                  disabled={mutating}
                  className="px-3 py-1 bg-red-900 hover:bg-red-800 disabled:opacity-50 rounded text-xs text-red-300"
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 充值订单 */}
      <section className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="font-semibold">充值订单</span>
            {submittedCount > 0 && (
              <span className="px-2 py-0.5 bg-yellow-900/80 text-yellow-300 text-xs rounded-full font-medium">
                {submittedCount} 条待审核
              </span>
            )}
          </div>
          <div className="flex gap-1">
            {[
              { key: "all", label: "全部" },
              { key: "submitted", label: "待审核" },
              { key: "pending", label: "待支付" },
              { key: "rejected", label: "已驳回" },
              { key: "credited", label: "已入账" },
            ].map((f) => (
              <button
                key={f.key}
                onClick={() => setStatusFilter(f.key)}
                className={`px-3 py-1 text-xs rounded ${
                  statusFilter === f.key
                    ? "bg-purple-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:bg-gray-700"
                }`}
              >
                {f.label}
                {f.key === "submitted" && submittedCount > 0 && ` (${submittedCount})`}
              </button>
            ))}
          </div>
        </div>

        {/* 审核备注输入 */}
        <div className="px-4 pb-3">
          <div className="flex items-center gap-2">
            <label className="text-gray-400 text-xs whitespace-nowrap">审核备注:</label>
            <input
              type="text"
              value={reviewerNote}
              onChange={(e) => setReviewerNote(e.target.value)}
              placeholder="可选，入账时附带备注"
              className="flex-1 px-2 py-1 bg-gray-800 border border-gray-700 rounded text-white text-xs placeholder:text-gray-600"
            />
          </div>
        </div>

        <table className="w-full text-sm">
          <thead className="bg-gray-800/50 text-gray-400">
            <tr>
              <th className="px-4 py-3 text-left">订单号</th>
              <th className="px-4 py-3 text-left">用户</th>
              <th className="px-4 py-3 text-left">套餐</th>
              <th className="px-4 py-3 text-left">金额</th>
              <th className="px-4 py-3 text-left">积分</th>
              <th className="px-4 py-3 text-left">状态</th>
              <th className="px-4 py-3 text-left">凭证</th>
              <th className="px-4 py-3 text-left">操作</th>
            </tr>
          </thead>
          <tbody>
            {sortedOrders.map((order) => {
              const st = STATUS_MAP[order.status] || { label: order.status, bg: "bg-gray-800", text: "text-gray-300" };
              return (
                <tr key={order.id} className={`border-t border-gray-800 ${order.status === "submitted" ? "bg-yellow-900/10" : ""}`}>
                  <td className="px-4 py-3 font-mono text-xs">{order.order_no}</td>
                  <td className="px-4 py-3">{order.username || "-"}</td>
                  <td className="px-4 py-3">{order.package_name || "-"}</td>
                  <td className="px-4 py-3">¥{(order.amount_fen / 100).toFixed(2)}</td>
                  <td className="px-4 py-3">{order.points}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded ${st.bg} ${st.text}`}>
                      {st.label}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {order.status === "submitted" || order.status === "credited" || order.proof_image ? (
                      <div className="flex flex-col gap-1 text-xs max-w-48">
                        {order.payment_remark && (
                          <div className="text-gray-400 truncate" title={order.payment_remark}>
                            备注: {order.payment_remark}
                          </div>
                        )}
                        {order.proof_image && (
                          <button
                            onClick={() => setPreviewImage(proofUrl(order.proof_image!))}
                            className="text-purple-400 hover:underline text-left"
                          >
                            查看截图
                          </button>
                        )}
                        {order.submitted_at && (
                          <div className="text-gray-500 text-[10px]">
                            提交: {order.submitted_at.replace("T", " ").slice(0, 19)}
                          </div>
                        )}
                      </div>
                    ) : (
                      <span className="text-gray-600 text-xs">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      {(order.status === "submitted" || order.status === "pending") && (
                        <>
                          <button
                            onClick={() => markPaid(order.order_no)}
                            disabled={mutating}
                            className="px-3 py-1 bg-green-600 hover:bg-green-700 disabled:opacity-50 rounded text-xs"
                          >
                            确认入账
                          </button>
                          <button
                            onClick={() => { setRejectTarget(order); setRejectReason(""); }}
                            disabled={mutating}
                            className="px-3 py-1 bg-red-800 hover:bg-red-700 disabled:opacity-50 rounded text-xs text-red-200"
                          >
                            驳回
                          </button>
                        </>
                      )}
                      {order.status === "credited" && order.reviewer_note && (
                        <span className="text-gray-500 text-xs" title={order.reviewer_note}>
                          备注: {order.reviewer_note}
                        </span>
                      )}
                      {order.status === "rejected" && order.reject_reason && (
                        <span className="text-red-400 text-xs" title={order.reject_reason}>
                          原因: {order.reject_reason}
                        </span>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
            {sortedOrders.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-500">暂无订单</td></tr>
            )}
          </tbody>
        </table>
      </section>

      {/* 驳回弹窗 */}
      {rejectTarget && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 w-full max-w-md space-y-4">
            <h3 className="text-lg font-semibold">驳回订单</h3>
            <div className="text-sm text-gray-400">
              订单号: <span className="font-mono text-white">{rejectTarget.order_no}</span>
            </div>
            <div className="text-sm text-gray-400">
              用户: {rejectTarget.username} · ¥{(rejectTarget.amount_fen / 100).toFixed(2)}
            </div>
            {rejectTarget.payment_remark && (
              <div className="text-sm text-gray-400">
                付款备注: {rejectTarget.payment_remark}
              </div>
            )}
            <div>
              <label className="block text-sm text-gray-400 mb-1">驳回原因 <span className="text-red-400">*</span></label>
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="请说明驳回原因，用户将看到此信息"
                rows={3}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm placeholder:text-gray-500 resize-none"
              />
            </div>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => { setRejectTarget(null); setRejectReason(""); }}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
              >
                取消
              </button>
              <button
                onClick={rejectOrder}
                disabled={mutating || !rejectReason.trim()}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-50 rounded-lg text-sm"
              >
                确认驳回
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 图片预览 */}
      {previewImage && (
        <div
          className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 cursor-pointer"
          onClick={() => setPreviewImage(null)}
        >
          <img src={previewImage} alt="付款凭证" className="max-w-full max-h-[90vh] rounded-lg shadow-2xl" />
        </div>
      )}
    </div>
  );
}
