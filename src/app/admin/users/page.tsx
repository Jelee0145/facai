"use client";

import { useState, useEffect } from "react";
import { useAuth } from "../auth-context";
import { toast } from "@/components/ui/toast";
import { logger } from "@/lib/logger";

function extractError(err: unknown, fallback = "操作失败"): string {
  const obj = err as Record<string, unknown>;
  if (typeof obj?.detail === "string") return obj.detail;
  if (Array.isArray(obj?.detail))
    return (obj.detail as Array<{ msg?: string }>).map((e) => e.msg ?? JSON.stringify(e)).join("; ");
  return fallback;
}

interface UserItem {
  id: number;
  username: string;
  phone: string;
  email: string;
  status: string;
  is_unlimited: boolean;
  last_login: string | null;
  created_at: string;
  note: string;
  balance: number;
  total_recharged: number;
  total_spent: number;
}

export default function UsersPage() {
  const { fetchWithAuth } = useAuth();
  const [users, setUsers] = useState<UserItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 创建用户弹窗
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({
    username: "",
    password: "",
    phone: "",
    email: "",
    note: "",
  });
  const [creating, setCreating] = useState(false);

  // 测试用户弹窗
  const [showTestUser, setShowTestUser] = useState(false);
  const [testUserCreds, setTestUserCreds] = useState<{ username: string; password: string } | null>(null);
  const [testUserLoading, setTestUserLoading] = useState(false);

  // 详情弹窗
  const [detailUser, setDetailUser] = useState<UserItem | null>(null);

  // 编辑备注弹窗
  const [editNoteUser, setEditNoteUser] = useState<UserItem | null>(null);
  const [editNote, setEditNote] = useState("");

  // 修改密码弹窗
  const [showChangePwd, setShowChangePwd] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [changingPwd, setChangingPwd] = useState(false);

  const load = () => {
    setLoading(true);
    setError(null);
    fetchWithAuth("/api/admin/users")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<{ users: UserItem[] }>;
      })
      .then((d) => setUsers(d.users || []))
      .catch((e) => {
        setError("加载失败");
        logger.error("Failed to load users:", e);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  // 创建用户
  const handleCreate = async () => {
    if (!createForm.username.trim()) {
      toast.warning("用户名不能为空");
      return;
    }
    if (!createForm.password) {
      toast.warning("密码不能为空");
      return;
    }
    setCreating(true);
    try {
      const r = await fetchWithAuth("/api/admin/users", {
        method: "POST",
        body: JSON.stringify(createForm),
      });
      if (!r.ok) {
        const err: Record<string, unknown> = await r.json().catch(() => ({}));
        toast.error(extractError(err, "创建失败"));
        return;
      }
      toast.success("用户创建成功");
      setShowCreate(false);
      setCreateForm({ username: "", password: "", phone: "", email: "", note: "" });
      load();
    } catch {
      toast.error("网络错误");
    } finally {
      setCreating(false);
    }
  };

  // 生成测试用户
  const handleCreateTestUser = async () => {
    setTestUserLoading(true);
    try {
      const r = await fetchWithAuth("/api/admin/users/test", { method: "POST" });
      if (!r.ok) {
        const err: Record<string, unknown> = await r.json().catch(() => ({}));
        toast.error(extractError(err, "创建失败"));
        return;
      }
      const data = (await r.json()) as { username: string; password: string; existed: boolean };
      setTestUserCreds({ username: data.username, password: data.password });
      toast.success(data.existed ? "测试用户已重置" : "测试用户已创建");
      load();
    } catch {
      toast.error("网络错误");
    } finally {
      setTestUserLoading(false);
    }
  };

  // 销毁测试用户
  const handleDeleteTestUser = async () => {
    if (!confirm("确定销毁测试用户？此操作不可撤销。")) return;
    try {
      const r = await fetchWithAuth("/api/admin/users/test", { method: "DELETE" });
      if (!r.ok) {
        const err: Record<string, unknown> = await r.json().catch(() => ({}));
        toast.error(extractError(err, "销毁失败"));
        return;
      }
      setTestUserCreds(null);
      setShowTestUser(false);
      toast.success("测试用户已销毁");
      load();
    } catch {
      toast.error("网络错误");
    }
  };

  // 冻结/解冻
  const toggleStatus = async (user: UserItem) => {
    const newStatus = user.status === "active" ? "frozen" : "active";
    const action = newStatus === "frozen" ? "冻结" : "解冻";
    if (!confirm(`确定${action}用户 "${user.username}"？`)) return;
    try {
      const r = await fetchWithAuth(`/api/admin/users/${user.id}/status`, {
        method: "PUT",
        body: JSON.stringify({ status: newStatus }),
      });
      if (!r.ok) {
        toast.error(`${action}失败`);
        return;
      }
      toast.success(`已${action}`);
      load();
    } catch {
      toast.error("网络错误");
    }
  };

  // 删除用户
  const deleteUser = async (user: UserItem) => {
    if (!confirm(`确定删除用户 "${user.username}"？此操作不可撤销，将删除该用户的所有数据（积分、订单、生成记录）。`)) return;
    try {
      const r = await fetchWithAuth(`/api/admin/users/${user.id}`, { method: "DELETE" });
      if (!r.ok) {
        const err: Record<string, unknown> = await r.json().catch(() => ({}));
        toast.error(extractError(err, "删除失败"));
        return;
      }
      toast.success("用户已删除");
      load();
    } catch {
      toast.error("网络错误");
    }
  };

  // 保存备注
  const saveNote = async () => {
    if (!editNoteUser) return;
    try {
      const r = await fetchWithAuth(`/api/admin/users/${editNoteUser.id}/note`, {
        method: "PUT",
        body: JSON.stringify({ note: editNote }),
      });
      if (!r.ok) {
        toast.error("备注保存失败");
        return;
      }
      toast.success("备注已更新");
      setEditNoteUser(null);
      load();
    } catch {
      toast.error("网络错误");
    }
  };

  // 修改管理员密码
  const handleChangePassword = async () => {
    if (!newPassword.trim()) {
      toast.warning("请输入新密码");
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.warning("两次输入的密码不一致");
      return;
    }
    setChangingPwd(true);
    try {
      const r = await fetchWithAuth("/api/admin/change-password", {
        method: "PUT",
        body: JSON.stringify({ new_password: newPassword }),
      });
      if (!r.ok) {
        const err: Record<string, unknown> = await r.json().catch(() => ({}));
        toast.error(extractError(err, "修改失败"));
        return;
      }
      toast.success("密码修改成功，请重新登录");
      setShowChangePwd(false);
      setNewPassword("");
      setConfirmPassword("");
      // 强制重新登录
      window.location.href = "/admin/login";
    } catch {
      toast.error("网络错误");
    } finally {
      setChangingPwd(false);
    }
  };

  const formatDate = (s: string | null) => {
    if (!s) return "-";
    try {
      return new Date(s + (s.includes("Z") || s.includes("+") ? "" : "Z")).toLocaleString("zh-CN");
    } catch {
      return s;
    }
  };

  return (
    <div>
      {/* 顶部标题栏 */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">👥 账号管理</h1>
        <div className="flex gap-3">
          <button
            onClick={() => setShowTestUser(true)}
            className="px-4 py-2 bg-amber-700 hover:bg-amber-600 rounded-lg text-sm font-medium"
          >
            🧪 测试用户
          </button>
          <button
            onClick={() => setShowChangePwd(true)}
            className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm font-medium"
          >
            🔒 修改密码
          </button>
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm font-medium"
          >
            + 创建用户
          </button>
        </div>
      </div>

      {/* 创建用户表单 */}
      {showCreate && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <input
              type="text"
              placeholder="用户名 (3-50字符)"
              value={createForm.username}
              onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
            />
            <input
              type="password"
              placeholder="密码 (任意长度)"
              value={createForm.password}
              onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
            />
            <input
              type="text"
              placeholder="手机号 (可选)"
              value={createForm.phone}
              onChange={(e) => setCreateForm({ ...createForm, phone: e.target.value })}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
            />
            <input
              type="text"
              placeholder="邮箱 (可选)"
              value={createForm.email}
              onChange={(e) => setCreateForm({ ...createForm, email: e.target.value })}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
            />
          </div>
          <input
            type="text"
            placeholder="备注 (可选)"
            value={createForm.note}
            onChange={(e) => setCreateForm({ ...createForm, note: e.target.value })}
            className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
          />
          <div className="flex gap-2">
            <button
              onClick={handleCreate}
              disabled={creating}
              className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg text-sm disabled:opacity-50"
            >
              {creating ? "创建中..." : "确认创建"}
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* 错误提示 */}
      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-xl p-4 mb-6 text-red-400">
          加载失败，请检查网络连接
          <button onClick={load} className="ml-3 underline hover:text-red-300">
            重试
          </button>
        </div>
      )}

      {/* 用户列表 */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-800/50">
              <tr className="text-left text-gray-400">
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">用户名</th>
                <th className="px-4 py-3">手机</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">余额</th>
                <th className="px-4 py-3">注册时间</th>
                <th className="px-4 py-3">最后登录</th>
                <th className="px-4 py-3">备注</th>
                <th className="px-4 py-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-t border-gray-800 hover:bg-gray-800/30">
                  <td className="px-4 py-3 text-gray-500">{u.id}</td>
                  <td className="px-4 py-3 font-medium">
                    <button
                      onClick={() => setDetailUser(u)}
                      className="hover:text-purple-400 transition"
                    >
                      {u.username}
                    </button>
                    {u.is_unlimited && (
                      <span className="ml-1 px-1.5 py-0.5 rounded text-[10px] bg-yellow-900/50 text-yellow-400">
                        不限量
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-400">{u.phone || "-"}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded text-xs ${
                        u.status === "active"
                          ? "bg-green-900/50 text-green-400"
                          : "bg-red-900/50 text-red-400"
                      }`}
                    >
                      {u.status === "active" ? "正常" : "冻结"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-400">
                    {u.is_unlimited ? "∞" : u.balance}
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {formatDate(u.created_at)}
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs">
                    {formatDate(u.last_login)}
                  </td>
                  <td className="px-4 py-3 text-gray-400 max-w-[120px] truncate">
                    {u.note || (
                      <button
                        onClick={() => {
                          setEditNoteUser(u);
                          setEditNote("");
                        }}
                        className="text-gray-600 hover:text-gray-400 text-xs"
                      >
                        + 添加
                      </button>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => {
                          setEditNoteUser(u);
                          setEditNote(u.note);
                        }}
                        className="text-xs px-2 py-1 rounded bg-gray-800 hover:bg-gray-700"
                        title="编辑备注"
                      >
                        备注
                      </button>
                      <button
                        onClick={() => toggleStatus(u)}
                        className={`text-xs px-2 py-1 rounded ${
                          u.status === "active"
                            ? "bg-yellow-900/30 hover:bg-yellow-900/50 text-yellow-400"
                            : "bg-green-900/30 hover:bg-green-900/50 text-green-400"
                        }`}
                      >
                        {u.status === "active" ? "冻结" : "解冻"}
                      </button>
                      <button
                        onClick={() => deleteUser(u)}
                        className="text-xs px-2 py-1 rounded bg-red-900/30 hover:bg-red-900/50 text-red-400"
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {loading && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-gray-500">
                    加载中...
                  </td>
                </tr>
              )}
              {!loading && users.length === 0 && (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-gray-500">
                    暂无用户
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 用户详情弹窗 */}
      {detailUser && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={(e) => {
          if (e.target !== e.currentTarget) return;
          setDetailUser(null);
        }}>
          <div
            className="bg-gray-900 border border-gray-800 rounded-xl p-6 w-full max-w-md space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">用户详情</h2>
              <button
                onClick={() => setDetailUser(null)}
                className="text-gray-500 hover:text-white text-xl"
              >
                ✕
              </button>
            </div>
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-400">ID</span>
                <span>{detailUser.id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">用户名</span>
                <span>{detailUser.username}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">密码</span>
                <span className="text-gray-500">••••••••</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">手机号</span>
                <span>{detailUser.phone || "-"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">邮箱</span>
                <span>{detailUser.email || "-"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">状态</span>
                <span
                  className={`px-2 py-0.5 rounded text-xs ${
                    detailUser.status === "active"
                      ? "bg-green-900/50 text-green-400"
                      : "bg-red-900/50 text-red-400"
                  }`}
                >
                  {detailUser.status === "active" ? "正常" : "冻结"}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">不限量</span>
                <span>{detailUser.is_unlimited ? "是" : "否"}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">余额</span>
                <span>{detailUser.is_unlimited ? "∞" : detailUser.balance}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">累计充值</span>
                <span>{detailUser.total_recharged}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">累计消费</span>
                <span>{detailUser.total_spent}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">注册时间</span>
                <span>{formatDate(detailUser.created_at)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">最后登录</span>
                <span>{formatDate(detailUser.last_login)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">备注</span>
                <span className="max-w-[200px] text-right">{detailUser.note || "-"}</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 编辑备注弹窗 */}
      {editNoteUser && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={(e) => {
          if (e.target !== e.currentTarget) return;
          if (window.getSelection()?.toString()) return;
          setEditNoteUser(null);
        }}>
          <div
            className="bg-gray-900 border border-gray-800 rounded-xl p-6 w-full max-w-md space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-lg font-bold">编辑备注 — {editNoteUser.username}</h2>
            <textarea
              value={editNote}
              onChange={(e) => setEditNote(e.target.value)}
              placeholder="输入备注内容..."
              rows={3}
              maxLength={500}
              className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm resize-none"
            />
            <div className="flex gap-2">
              <button
                onClick={saveNote}
                className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm"
              >
                保存
              </button>
              <button
                onClick={() => setEditNoteUser(null)}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 修改管理员密码弹窗 */}
      {showChangePwd && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={(e) => {
          if (e.target !== e.currentTarget) return;
          if (window.getSelection()?.toString()) return;
          setShowChangePwd(false);
        }}>
          <div
            className="bg-gray-900 border border-gray-800 rounded-xl p-6 w-full max-w-md space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">🔒 修改管理员密码</h2>
              <button
                onClick={() => setShowChangePwd(false)}
                className="text-gray-500 hover:text-white text-xl"
              >
                ✕
              </button>
            </div>
            <div className="space-y-3">
              <input
                type="password"
                placeholder="输入新密码"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
              />
              <input
                type="password"
                placeholder="确认新密码"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleChangePassword}
                disabled={changingPwd}
                className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm disabled:opacity-50"
              >
                {changingPwd ? "修改中..." : "确认修改"}
              </button>
              <button
                onClick={() => setShowChangePwd(false)}
                className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 测试用户弹窗 */}
      {showTestUser && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={(e) => {
          if (e.target !== e.currentTarget) return;
          setShowTestUser(false);
          setTestUserCreds(null);
        }}>
          <div
            className="bg-gray-900 border border-gray-800 rounded-xl p-6 w-full max-w-md space-y-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold">🧪 无限积分测试用户</h2>
              <button
                onClick={() => { setShowTestUser(false); setTestUserCreds(null); }}
                className="text-gray-500 hover:text-white text-xl"
              >
                ✕
              </button>
            </div>
            {testUserCreds ? (
              <div className="space-y-3 text-sm">
                <div className="bg-yellow-900/30 border border-yellow-800 rounded-lg p-3 text-yellow-400">
                  测试用户已创建，可用于前台功能测试
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">用户名</span>
                  <span className="font-mono">{testUserCreds.username}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-400">密码</span>
                  <span className="font-mono">{testUserCreds.password}</span>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleDeleteTestUser}
                    className="px-4 py-2 bg-red-600 hover:bg-red-700 rounded-lg text-sm"
                  >
                    销毁测试用户
                  </button>
                  <button
                    onClick={() => { setShowTestUser(false); }}
                    className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
                  >
                    关闭
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-gray-400">
                  创建一个用户名为 <code className="font-mono bg-gray-800 px-1.5 py-0.5 rounded">test</code>、密码为 <code className="font-mono bg-gray-800 px-1.5 py-0.5 rounded">test123</code> 的无限积分用户，用于前台功能测试。
                </p>
                <div className="flex gap-2">
                  <button
                    onClick={handleCreateTestUser}
                    disabled={testUserLoading}
                    className="px-4 py-2 bg-amber-600 hover:bg-amber-700 rounded-lg text-sm disabled:opacity-50"
                  >
                    {testUserLoading ? "创建中..." : "创建"}
                  </button>
                  <button
                    onClick={() => setShowTestUser(false)}
                    className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm"
                  >
                    取消
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
