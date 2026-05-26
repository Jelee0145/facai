"use client";

import { createContext, useContext, useState, useEffect, useRef, ReactNode } from "react";
import { toast } from "@/components/ui/toast";

interface AuthContextType {
  user: Record<string, unknown> | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => void;
  fetchWithAuth: (url: string, options?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  isLoading: true,
  login: async () => false,
  logout: () => { },
  fetchWithAuth: async () => new Response(),
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Record<string, unknown> | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const csrfTokenRef = useRef("");

  // 初始化时通过 /api/admin/me 检测会话状态
  useEffect(() => {
    fetch("/api/admin/me")
      .then((r) => {
        if (r.ok) return r.json();
        throw new Error("not authenticated");
      })
      .then((data) => {
        if (data.csrf_token) csrfTokenRef.current = data.csrf_token;
        setUser(data);
      })
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false));
  }, []);

  const login = async (username: string, password: string): Promise<boolean> => {
    try {
      const resp = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({})) as Record<string, unknown>;
        toast.error(String(err.detail || "登录失败"));
        return false;
      }
      const data = await resp.json();
      if (data.csrf_token) csrfTokenRef.current = data.csrf_token;
      const userObj = data.user || { username: data.username, role: data.role };
      setUser(userObj);
      return true;
    } catch {
      toast.error("网络错误，请检查后端服务是否运行");
      return false;
    }
  };

  const logout = async () => {
    try {
      await fetch("/api/admin/logout", { method: "POST" });
    } catch {
      // 即使后端不可达也清除前端状态
    }
    setUser(null);
  };

  const fetchWithAuth = async (url: string, options: RequestInit = {}): Promise<Response> => {
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string> || {}),
    };
    if (options.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    // inject CSRF token for state-changing requests
    const method = (options.method || "GET").toUpperCase();
    if (["POST", "PUT", "DELETE"].includes(method) && csrfTokenRef.current) {
      headers["X-CSRF-Token"] = csrfTokenRef.current;
    }
    const resp = await fetch(url, { ...options, headers });
    if (resp.status === 401) {
      setUser(null);
    }
    return resp;
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout, fetchWithAuth }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
