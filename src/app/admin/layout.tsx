"use client";

import { ReactNode } from "react";
import Link from "next/link";
import { AuthProvider, useAuth } from "./auth-context";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

const menu = [
  { label: "仪表盘", path: "/admin" },
  { label: "API Keys", path: "/admin/keys" },
  { label: "计费管理", path: "/admin/billing" },
  { label: "LLM 设置", path: "/admin/llm" },
  { label: "历史记录", path: "/admin/history" },
];

function AdminLayoutInner({ children }: { children: ReactNode }) {
  const { user, isLoading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && !user && pathname !== "/admin/login") {
      router.replace("/admin/login");
    }
  }, [isLoading, user, pathname, router]);

  // 已登录用户访问登录页时，重定向到仪表盘
  useEffect(() => {
    if (!isLoading && user && pathname === "/admin/login") {
      router.replace("/admin");
    }
  }, [isLoading, user, pathname, router]);

  const handleLogout = () => {
    logout();
    router.replace("/admin/login");
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center text-white">
        <span className="animate-spin text-2xl mr-2">⏳</span> 加载中...
      </div>
    );
  }

  if (pathname === "/admin/login") {
    return <>{children}</>;
  }

  if (!user) {
    return null;
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white flex">
      <aside className="w-64 bg-gray-900 border-r border-gray-800 flex flex-col">
        <div className="p-6 border-b border-gray-800">
          <h1 className="text-xl font-bold bg-gradient-to-r from-purple-400 to-pink-400 bg-clip-text text-transparent">
            AI 电商图管理
          </h1>
        </div>
        <nav className="flex-1 p-4 space-y-2">
          {menu.map((item) => (
            <Link
              key={item.path}
              href={item.path}
              className={`block px-4 py-2 rounded-lg transition ${
                pathname === item.path
                  ? "bg-purple-500/20 text-purple-300 border border-purple-500/30"
                  : "text-gray-400 hover:text-white hover:bg-gray-800"
              }`}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="p-4 border-t border-gray-800">
          <button
            onClick={handleLogout}
            className="w-full px-4 py-2 text-sm text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition"
          >
            退出登录
          </button>
        </div>
      </aside>
      <main className="flex-1 p-8 overflow-auto">{children}</main>
    </div>
  );
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <AdminLayoutInner>{children}</AdminLayoutInner>
    </AuthProvider>
  );
}
