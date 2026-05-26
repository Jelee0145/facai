import { useEffect, useRef } from "react";

type SSEHandler = {
  onProgress?: (data: unknown) => void;
  onComplete?: (data: unknown) => void;
  onError?: (error: string) => void;
};

export function useSSE(taskId: string | null, handlers: SSEHandler) {
  const handlersRef = useRef(handlers);

  useEffect(() => {
    handlersRef.current = handlers;
  });

  useEffect(() => {
    if (!taskId) return;

    const url = `/api/generate/status/${taskId}/stream`;
    const source = new EventSource(url);

    source.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const status = data.status;
        if (status === "completed") {
          handlersRef.current.onComplete?.(data);
          source.close();
        } else if (status === "failed" || status === "timeout") {
          handlersRef.current.onError?.(data.error || "Generation failed");
          source.close();
        } else {
          handlersRef.current.onProgress?.(data);
        }
      } catch {
        // ignore
      }
    };

    source.onerror = () => {
      handlersRef.current.onError?.("Connection lost");
      source.close();
    };

    return () => {
      source.close();
    };
  }, [taskId]);
}
