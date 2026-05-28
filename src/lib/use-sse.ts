import { useEffect, useRef } from "react";

type SSEHandler = {
  onProgress?: (data: unknown) => void;
  onComplete?: (data: unknown) => void;
  onError?: (error: string) => void;
  onOpen?: () => void;
};

const MAX_RECONNECT = 3;
const RECONNECT_INTERVAL = 5000;

export function useSSE(taskId: string | null, handlers: SSEHandler) {
  const handlersRef = useRef(handlers);

  useEffect(() => {
    handlersRef.current = handlers;
  });

  useEffect(() => {
    if (!taskId) return;

    let reconnectCount = 0;
    let closed = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    let currentSource: EventSource | null = null;

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

        // Check HTTP status from the event source state
        if (source.readyState === EventSource.CLOSED) {
          // Connection was closed by server — check session status
          fetch("/api/auth/me", { credentials: "include" })
            .then((res) => {
              if (res.status === 401) {
                handlersRef.current.onError?.("会话已过期，请重新登录");
                closed = true;
                return;
              }
              return res.json();
            })
            .then((data) => {
              if (!closed && data && !data?.user) {
                handlersRef.current.onError?.("会话已过期，请重新登录");
                closed = true;
              } else if (!closed) {
                if (reconnectCount < MAX_RECONNECT) {
                  reconnectCount++;
                  console.warn(`SSE disconnected, reconnecting (${reconnectCount}/${MAX_RECONNECT})...`);
                  timeoutId = setTimeout(connect, RECONNECT_INTERVAL);
                } else {
                  handlersRef.current.onError?.("Connection lost after retries");
                  closed = true;
                }
              }
            })
            .catch(() => {
              if (!closed) {
                handlersRef.current.onError?.("Connection lost after retries");
                closed = true;
              }
            });
        } else if (reconnectCount < MAX_RECONNECT) {
          reconnectCount++;
          console.warn(`SSE disconnected, reconnecting (${reconnectCount}/${MAX_RECONNECT})...`);
          timeoutId = setTimeout(connect, RECONNECT_INTERVAL);
        } else {
          handlersRef.current.onError?.("Connection lost after retries");
          closed = true;
        }
      };
    }

    connect();

    return () => {
      closed = true;
      clearTimeout(timeoutId);
      currentSource?.close();
      currentSource = null;
    };
  }, [taskId]);
}
