import { useEffect, useCallback } from "react";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  containerClassName?: string;
  noHeader?: boolean;
  variant?: "page" | "admin";
}

export function Modal({ open, onClose, title, children, containerClassName = "", noHeader = false, variant = "page" }: ModalProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose],
  );

  useEffect(() => {
    if (open) {
      document.addEventListener("keydown", handleKeyDown);
      return () => document.removeEventListener("keydown", handleKeyDown);
    }
  }, [open, handleKeyDown]);

  if (!open) return null;

  const container = variant === "admin"
    ? "bg-gray-900 border border-gray-700 rounded-2xl max-h-[85vh] overflow-hidden flex flex-col"
    : "bg-slate-800 rounded-2xl border border-white/10 max-h-[85vh] overflow-hidden flex flex-col";

  const headerBorder = variant === "admin" ? "border-gray-800" : "border-white/10";
  const closeBtn = variant === "admin" ? "text-gray-400 hover:text-white" : "text-white/60 hover:text-white";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4"
      onClick={(e) => {
        if (e.target !== e.currentTarget) return;
        const sel = window.getSelection();
        if (sel && sel.toString().length > 0) return;
        onClose();
      }}
    >
      <div
        className={`${container} ${containerClassName}`}
        onClick={(e) => e.stopPropagation()}
      >
        {!noHeader && title && (
          <div className={`flex items-center justify-between px-6 py-4 border-b ${headerBorder} shrink-0`}>
            <h2 className="text-lg font-bold text-white">{title}</h2>
            <button
              onClick={onClose}
              className={`${closeBtn} text-2xl leading-none`}
            >
              &times;
            </button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto p-6">
          {children}
        </div>
      </div>
    </div>
  );
}
