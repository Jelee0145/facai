"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useState, useEffect } from "react";
import { useAuth } from "../auth-context";

export default function HistoryPage() {
  const { fetchWithAuth } = useAuth();
  const [data, setData] = useState<any>({ items: [], total: 0 });
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [detail, setDetail] = useState<any>(null);

  const load = () => {
    const params = new URLSearchParams({ page: String(page), per_page: "20" });
    if (status) params.set("status", status);
    if (search) params.set("search", search);
    fetchWithAuth(`/api/admin/history?${params}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((d) => setData({ items: d.items || [], total: d.total || 0 }))
      .catch(() => {});
  };

  useEffect(() => { load(); }, [page, status]);

  const openDetail = async (id: number) => {
    const r = await fetchWithAuth(`/api/admin/history/${id}`);
    if (!r.ok) return;
    setDetail(await r.json());
  };

  const statusColors: Record<string, string> = {
    completed: "bg-green-900/50 text-green-400",
    failed: "bg-red-900/50 text-red-400",
    partial: "bg-yellow-900/50 text-yellow-400",
    pending: "bg-gray-700 text-gray-400",
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">📋 生成历史</h1>

      <div className="flex gap-3 mb-4">
        <select
          value={status}
          onChange={(e) => { setStatus(e.target.value); setPage(1); }}
          className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
        >
          <option value="">全部状态</option>
          <option value="completed">已完成</option>
          <option value="failed">失败</option>
          <option value="partial">部分成功</option>
        </select>
        <input
          type="text"
          placeholder="搜索商品类型..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (setPage(1), load())}
          className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
        />
        <button onClick={() => { setPage(1); load(); }} className="px-4 py-2 bg-purple-600 hover:bg-purple-700 rounded-lg text-sm">搜索</button>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-800/50">
            <tr className="text-left text-gray-400">
              <th className="px-4 py-3">时间</th>
              <th className="px-4 py-3">商品</th>
              <th className="px-4 py-3">国家</th>
              <th className="px-4 py-3">状态</th>
              <th className="px-4 py-3">图片</th>
              <th className="px-4 py-3">耗时</th>
              <th className="px-4 py-3">LLM</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((h: any) => (
              <tr key={h.id} className="border-t border-gray-800">
                <td className="px-4 py-3 text-gray-400 text-xs">{h.created_at?.replace("T", " ").slice(0, 19)}</td>
                <td className="px-4 py-3">{h.product_type || "-"}</td>
                <td className="px-4 py-3">{h.country || "-"}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded text-xs ${statusColors[h.status] || "bg-gray-700 text-gray-400"}`}>
                    {h.status === "completed" ? "完成" : h.status === "failed" ? "失败" : h.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-gray-400">{h.success_count}/{h.total_images}</td>
                <td className="px-4 py-3 text-gray-400">{h.elapsed_seconds}s</td>
                <td className="px-4 py-3">
                  {h.llm_response ? (
                    <span className="text-xs text-green-500">已用</span>
                  ) : h.llm_request ? (
                    <span className="text-xs text-yellow-500">请求中</span>
                  ) : (
                    <span className="text-xs text-gray-600">-</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <button
                    onClick={() => openDetail(h.id)}
                    className="px-3 py-1 text-xs bg-gray-700 hover:bg-gray-600 rounded"
                  >
                    详情
                  </button>
                </td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-gray-500">暂无记录</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {data.total > 20 && (
        <div className="flex items-center justify-between mt-4 text-sm text-gray-400">
          <span>共 {data.total} 条记录</span>
          <div className="flex gap-2">
            <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="px-3 py-1 bg-gray-800 rounded disabled:opacity-30">上一页</button>
            <span className="px-3 py-1">第 {page} 页</span>
            <button disabled={page * 20 >= data.total} onClick={() => setPage(page + 1)} className="px-3 py-1 bg-gray-800 rounded disabled:opacity-30">下一页</button>
          </div>
        </div>
      )}

      {detail && (
        <HistoryDetailModal
          detail={detail}
          onClose={() => setDetail(null)}
        />
      )}
    </div>
  );
}

function HistoryDetailModal({ detail, onClose }: { detail: any; onClose: () => void }) {
  const llmReq = detail.llm_request;
  const llmResp = detail.llm_response;
  const tasks = detail.tasks_detail || [];

  // LLM 请求中提取 system 和 user 消息
  const systemMsg = Array.isArray(llmReq)
    ? llmReq.find((m: any) => m.role === "system")?.content || ""
    : "";
  const userMsg = Array.isArray(llmReq)
    ? llmReq.find((m: any) => m.role === "user")?.content || ""
    : "";

  const [activeTab, setActiveTab] = useState<"llm" | "tasks" | "meta">("llm");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={onClose}>
      <div
        className="bg-gray-900 border border-gray-700 rounded-2xl w-full max-w-4xl max-h-[85vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <h2 className="text-lg font-bold">任务详情 #{detail.id}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">&times;</button>
        </div>

        {/* tabs */}
        <div className="flex gap-1 px-6 pt-4 pb-0 border-b border-gray-800">
          {[
            { key: "llm", label: "LLM 调用链" },
            { key: "tasks", label: `提示词 (${tasks.length})` },
            { key: "meta", label: "生成信息" },
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as any)}
              className={`px-4 py-2 text-sm rounded-t-lg transition-colors ${
                activeTab === tab.key
                  ? "bg-gray-800 text-white border border-gray-700 border-b-gray-800"
                  : "text-gray-400 hover:text-white"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {activeTab === "llm" && (
            <>
              <Section title="LLM 请求消息">
                <CodeBlock label="System Prompt">{systemMsg}</CodeBlock>
                <CodeBlock label="User Prompt">
                  {typeof userMsg === "string" ? userMsg : JSON.stringify(userMsg, null, 2)}
                </CodeBlock>
              </Section>
              {llmResp && (
                <Section title="LLM 响应">
                  <CodeBlock label="Scene Config">
                    {JSON.stringify(llmResp.scene_config, null, 2)}
                  </CodeBlock>
                  <CodeBlock label="Metadata">
                    {JSON.stringify(llmResp.metadata, null, 2)}
                  </CodeBlock>
                </Section>
              )}
              {!llmResp && !llmReq && (
                <p className="text-gray-500 text-sm">该记录未使用 LLM</p>
              )}
            </>
          )}

          {activeTab === "tasks" && (
            <div className="space-y-3">
              {tasks.length === 0 && (
                <p className="text-gray-500 text-sm">暂无任务详情</p>
              )}
              {tasks.map((t: any, i: number) => (
                <div key={i} className="bg-gray-800 rounded-xl p-4 space-y-2">
                  <div className="flex items-center justify-between text-xs text-gray-400">
                    <span className="font-mono">#{t.index}</span>
                    {t.result_url && !t.result_url.startsWith("data:") && (
                      <a href={t.result_url} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline">查看图片</a>
                    )}
                  </div>
                  <CodeBlock label="发送的提示词">{t.prompt}</CodeBlock>
                  {t.reference_url && (
                    <p className="text-xs text-gray-500 truncate">参考图: {t.reference_url}</p>
                  )}
                  {t.result_url && (
                    <p className="text-xs text-gray-500 truncate">结果: {t.result_url}</p>
                  )}
                </div>
              ))}
            </div>
          )}

          {activeTab === "meta" && (
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div className="space-y-3">
                <MetaItem label="任务 ID" value={detail.task_id} mono />
                <MetaItem label="商品" value={detail.product_type} />
                <MetaItem label="国家" value={detail.country} />
                <MetaItem label="模型" value={detail.model} />
                <MetaItem label="状态" value={detail.status} />
              </div>
              <div className="space-y-3">
                <MetaItem label="尺寸" value={detail.prompt_size} />
                <MetaItem label="分辨率" value={detail.prompt_resolution} />
                <MetaItem label="成功/总数" value={`${detail.success_count}/${detail.total_images}`} />
                <MetaItem label="耗时" value={`${detail.elapsed_seconds}s`} />
                <MetaItem label="创建时间" value={detail.created_at} />
              </div>
              {detail.error_msg && (
                <div className="col-span-2">
                  <CodeBlock label="错误信息">{detail.error_msg}</CodeBlock>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-gray-300">{title}</h3>
      {children}
    </div>
  );
}

function CodeBlock({ label, children }: { label?: string; children: React.ReactNode }) {
  const str = typeof children === "string" ? children : JSON.stringify(children, null, 2);
  return (
    <div>
      {label && <p className="text-xs text-gray-500 mb-1">{label}</p>}
      <pre className="bg-gray-950 border border-gray-800 rounded-lg p-3 text-xs text-gray-300 overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap font-mono leading-relaxed">{str}</pre>
    </div>
  );
}

function MetaItem({ label, value, mono }: { label: string; value?: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-xs text-gray-500">{label}</p>
      <p className={`text-white ${mono ? "font-mono text-xs" : "text-sm"}`}>{value || "-"}</p>
    </div>
  );
}
