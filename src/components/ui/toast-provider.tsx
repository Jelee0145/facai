"use client";

import { Toaster } from "@/components/ui/toast";

export function ToastProvider({ children }: { children: React.ReactNode }) {
  return (
    <>
      {children}
      <Toaster />
    </>
  );
}
