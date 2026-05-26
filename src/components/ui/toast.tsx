"use client";

import { useEffect, useState, useCallback } from "react";

export type ToastType = "success" | "error" | "warning";

export interface Toast {
  id: number;
  message: string;
  type: ToastType;
}

let nextId = 0;
const listeners: Set<(toast: Toast) => void> = new Set();

function emit(toast: Toast) {
  listeners.forEach((fn) => fn(toast));
}

const typeConfig: Record<ToastType, { bg: string; border: string }> = {
  success: { bg: "bg-green-600/90", border: "border-green-400" },
  error: { bg: "bg-red-600/90", border: "border-red-400" },
  warning: { bg: "bg-amber-600/90", border: "border-amber-400" },
};

export function showToast(message: string, type: ToastType = "error") {
  emit({ id: nextId++, message, type });
}

export const toast = {
  success: (msg: string) => showToast(msg, "success"),
  error: (msg: string) => showToast(msg, "error"),
  warning: (msg: string) => showToast(msg, "warning"),
};

export function ToastItem({ toast, onRemove }: { toast: Toast; onRemove: (id: number) => void }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    requestAnimationFrame(() => setVisible(true));
    const timer = setTimeout(() => {
      setVisible(false);
      setTimeout(() => onRemove(toast.id), 300);
    }, 2500);
    return () => clearTimeout(timer);
  }, [toast.id, onRemove]);

  const config = typeConfig[toast.type];

  return (
    <div
      role="alert"
      className={`${config.bg} border ${config.border} text-white px-5 py-3 rounded-xl shadow-xl backdrop-blur-sm text-sm font-medium transition-all duration-300 ${
        visible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"
      }`}
    >
      {toast.message}
    </div>
  );
}

export function Toaster() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((t: Toast) => {
    setToasts((prev) => [...prev, t]);
  }, []);

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  useEffect(() => {
    listeners.add(addToast);
    return () => {
      listeners.delete(addToast);
    };
  }, [addToast]);

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] flex flex-col gap-2 items-center pointer-events-none">
      {toasts.map((t) => (
        <div key={t.id} className="pointer-events-auto">
          <ToastItem toast={t} onRemove={removeToast} />
        </div>
      ))}
    </div>
  );
}
