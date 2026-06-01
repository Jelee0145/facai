import { useEffect, useRef } from "react";

type SSEHandler = {
  onProgress?: (data: unknown) => void;
  onComplete?: (data: unknown) => void;
  onError?: (error: string) => void;
  onOpen?: () => void;
};

const RECONNECT_BASE_DELAY = 2000;
const RECONNECT_MAX_DELAY = 30000;

export function useSSE(taskId: string | null, handlers: SSEHandler) {
  const handlersRef = useRef(handlers);

  useEffect(() => {
    handlersRef.current = handlers;
  });

  useEffect(() => {
    if (!taskId) return;

    let reconnectCount = 0;
    let closed = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    let currentSource: EventSource | null = null;

    const clearReconnectTimer = () => {
      if (timeoutId) {
        clearTimeout(timeoutId);
        timeoutId = null;
      }
    };

    const scheduleReconnect = () => {
      if (closed) return;
      reconnectCount += 1;
      const delay = Math.min(
        RECONNECT_BASE_DELAY * Math.pow(2, Math.min(reconnectCount - 1, 4)),
        RECONNECT_MAX_DELAY,
      );
      console.warn(`SSE disconnected, reconnecting in ${Math.round(delay / 1000)}s...`);
      clearReconnectTimer();
      timeoutId = setTimeout(connect, delay);
    };

    const checkSession = async (): Promise<boolean> => {
      try {
        const res = await fetch("/api/auth/me", { credentials: "include" });
        if (res.status === 401) return false;
        if (!res.ok) return true;
        const data = await res.json().catch(() => null);
        return Boolean(data?.user);
      } catch {
        // Network checks can fail during the same transient outage that closed SSE.
        // Keep the generation attached and let the next reconnect recover.
        return true;
      }
    };

    function connect() {
      if (closed) return;

      const url = `/api/generate/status/${taskId}/stream`;
      const source = new EventSource(url);
      currentSource = source;

      source.onopen = () => {
        if (closed) return;
        // Reset reconnect counter on successful connection
        reconnectCount = 0;
        handlersRef.current.onOpen?.();
      };

      source.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const status = data.status;

          if (status === "completed") {
            handlersRef.current.onComplete?.(data);
            closed = true;
            source.close();
          } else if (status === "failed" || status === "timeout" || status === "error") {
            handlersRef.current.onError?.(data.error || "Generation failed");
            closed = true;
            source.close();
          } else {
            handlersRef.current.onProgress?.(data);
          }
        } catch {
          console.warn("[SSE] Failed to parse event data:", event.data);
        }
      };

      source.onerror = () => {
        source.close();
        currentSource = null;

        if (closed) return;

        void checkSession().then((sessionOk) => {
          if (closed) return;
          if (!sessionOk) {
            handlersRef.current.onError?.("会话已过期，请重新登录");
            closed = true;
            return;
          }
          scheduleReconnect();
        });
      };
    }

    connect();

    return () => {
      closed = true;
      clearReconnectTimer();
      currentSource?.close();
      currentSource = null;
    };
  }, [taskId]);
}
