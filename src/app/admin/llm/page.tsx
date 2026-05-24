"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import { useState, useEffect } from "react";
import { useAuth } from "../auth-context";

export default function LlmConfigPage() {
  const { fetchWithAuth } = useAuth();
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("qwen3-vl-flash");
  const [hasKey, setHasKey] = useState(false);
  const [status, setStatus] = useState<"loading" | "ok" | "error" | "unconfigured">("loading");
  const [showKey, setShowKey] = useState(false);
  const [savedKeyLength, setSavedKeyLength] = useState(0);
  const [originalMaskedKey, setOriginalMaskedKey] = useState("");
  const [testResult, setTestResult] = useState<{ success: boolean; reply?: string; error?: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = () => {
    setStatus("loading");
    fetchWithAuth("/api/admin/llm-config")
      .then((r) => r.json())
      .then((d) => {
        const masked = d.api_key || "";
        setApiKey(masked);
        setOriginalMaskedKey(masked);
        setModel(d.model || "qwen3-vl-flash");
        setHasKey(d.has_key || false);
        setSavedKeyLength(d.key_length || 0);
        setStatus(d.has_key ? "ok" : "unconfigured");
      })
      .catch(() => setStatus("error"));
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      const body: Record<string, string> = { model };
      if (apiKey !== originalMaskedKey) {
        body.api_key = apiKey;
      }
      const r = await fetchWithAuth("/api/admin/llm-config", {
        method: "PUT",
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        alert(err.detail || "保存失败");
        return;
      }
      load();
    } catch {
      alert("网络错误");
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await fetchWithAuth("/api/admin/llm-config/test", {
        method: "POST",
        body: JSON.stringify({ api_key: apiKey, model }),
      });
      const d = await r.json();
      setTestResult(d);
      if (d.success) {
        setStatus("ok");
      }
    } catch {
      setTestResult({ success: false, error: "网络错误" });
    } finally {
      setTesting(false);
    }
  };

  const statusBadge = () => {
    switch (status) {
      case "loading":
        return <span className="px-2 py-1 rounded text-xs bg-gray-700 text-gray-300">检测中...</span>;
      case "ok":
        return <span className="px-2 py-1 rounded text-xs bg-green-900/50 text-green-400">✅ 已连接</span>;
      case "error":
        return <span className="px-2 py-1 rounded text-xs bg-red-900/50 text-red-400">❌ 连接异常</span>;
      case "unconfigured":
        return <span className="px-2 py-1 rounded text-xs bg-yellow-900/50 text-yellow-400">⚠️ 未配置</span>;
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">🤖 LLM 智能配置</h1>
        <span>{statusBadge()}</span>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 space-y-5 max-w-xl">
        <p className="text-sm text-gray-400">
          配置阿里云百炼 LLM，用于智能分析商品并生成拍摄方案。配置后在商品生成时将自动调用 LLM 优化场景、标题和标签。
        </p>

        <div className="space-y-2">
          <label className="block text-sm text-gray-400">API Key</label>
          <div className="flex gap-2">
            <input
              type={showKey ? "text" : "password"}
              placeholder={hasKey ? "输入新 Key 以替换当前配置" : "输入阿里云百炼 API Key"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm font-mono"
              autoComplete="off"
            />
            <button
              type="button"
              onClick={() => setShowKey(!showKey)}
              className="px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-gray-400 hover:text-white text-sm"
              title={showKey ? "隐藏 Key" : "显示 Key"}
            >
              {showKey ? "隐藏" : "显示"}
            </button>
          </div>
          {hasKey && (
            <p className="text-xs text-gray-500">
              {apiKey === originalMaskedKey
                ? `当前已配置 ${savedKeyLength} 位 Key`
                : `已配置 ${savedKeyLength} 位 Key，输入新值将覆盖`}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <label className="block text-sm text-gray-400">模型名称</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm"
          >
            <option value="qwen3-vl-flash">qwen3-vl-flash（视觉模型，推荐）</option>
            <option value="qwen-vl-max">qwen-vl-max（视觉最强）</option>
            <option value="qwen-plus">qwen-plus（纯文本，无图时可用）</option>
            <option value="qwen-max">qwen-max（纯文本最强）</option>
          </select>
        </div>

        <div className="flex gap-3 pt-2">
          <button
            onClick={save}
            disabled={saving}
            className="px-5 py-2 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 rounded-lg text-sm font-medium"
          >
            {saving ? "保存中..." : "保存配置"}
          </button>
          <button
            onClick={testConnection}
            disabled={testing || !apiKey}
            className="px-5 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 rounded-lg text-sm"
          >
            {testing ? "测试中..." : "测试连接"}
          </button>
        </div>

        {testResult && (
          <div className={`p-4 rounded-lg text-sm ${
            testResult.success
              ? "bg-green-900/30 border border-green-800 text-green-300"
              : "bg-red-900/30 border border-red-800 text-red-300"
          }`}>
            {testResult.success ? (
              <>
                <p className="font-medium mb-1">✅ 连接成功</p>
                <p className="text-xs opacity-80">{testResult.reply}</p>
              </>
            ) : (
              <>
                <p className="font-medium mb-1">❌ 连接失败</p>
                <p className="text-xs opacity-80">{testResult.error}</p>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
