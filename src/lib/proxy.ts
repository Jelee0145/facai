import { NextRequest, NextResponse } from "next/server";
import { fetchWithRetry } from "@/lib/fetch";
import { withCircuitBreaker, CircuitOpenError } from "@/lib/circuit-breaker";
import { logger } from "@/lib/logger";

const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8001")
  .trim()
  .replace(/\s+/g, "")
  .replace(/\/+$/, "");
const API_AUTH_TOKEN = process.env.API_AUTH_TOKEN || "";
const MAX_BODY_SIZE = 10 * 1024 * 1024; // 10MB

function buildBackendUrl(path: string, search = "") {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${BACKEND_URL}${normalizedPath}${search}`;
}

export interface ProxyOptions {
  /** 路由路径前缀 (如 /api/generate、/admin)，会替换掉原始路径 */
  targetPrefix?: string;
  /** 是否转发 cookie 到后端 (登录相关路由需要) */
  forwardCookies?: boolean;
  /** 是否转发 set-cookie 到前端 (登录相关路由需要) */
  forwardSetCookie?: boolean;
  /** 是否启用 SSE streaming 支持 */
  handleStreaming?: boolean;
  /** 允许的方法，默认 GET/POST */
  allowedMethods?: string[];
  /**
   * 自定义后端路径，格式 `${BACKEND_URL}${path}${search}` 中的 path 部分。
   * 当设置此值时，targetPrefix 和原始路径都会被忽略。
   */
  customPath?: string;
}

/** Headers that should never be forwarded to the backend */
const HOP_BY_HOP_HEADERS = new Set([
  "host", "content-length", "transfer-encoding", "expect",
]);

/**
 * 通用后端代理函数
 * @param request 原始请求
 * @param method HTTP 方法
 * @param params 路由参数 (catch-all 的 params.path，或 undefined)
 * @param options 配置选项
 */
export async function proxyToBackend(
  request: NextRequest,
  method: string,
  params: { path: string[] } | undefined,
  options: ProxyOptions = {},
) {
  const {
    targetPrefix = "",
    forwardCookies = false,
    forwardSetCookie = false,
    handleStreaming = false,
    allowedMethods,
    customPath,
  } = options;

  if (allowedMethods && !allowedMethods.includes(method)) {
    return NextResponse.json({ error: "Method not allowed" }, { status: 405 });
  }

  try {
    let targetUrl: string;
    if (customPath) {
      targetUrl = buildBackendUrl(customPath);
    } else {
      const url = new URL(request.url);
      const subPath = params ? params.path.join("/") : "";
      const path = targetPrefix
        ? `${targetPrefix}${subPath ? `/${subPath}` : ""}`
        : url.pathname;
      targetUrl = buildBackendUrl(path, url.search);
      logger.log(`[PROXY] ${method} ${url.pathname} -> ${targetUrl}`);
    }

    // Build request headers, filtering based on forwardCookies
    const headers: Record<string, string> = {};
    const stripHeaders = forwardCookies
      ? HOP_BY_HOP_HEADERS
      : new Set([...HOP_BY_HOP_HEADERS, "cookie", "authorization"]);

    request.headers.forEach((value, key) => {
      if (!stripHeaders.has(key.toLowerCase())) {
        headers[key] = value;
      }
    });

    if (API_AUTH_TOKEN) {
      headers["X-API-Auth"] = API_AUTH_TOKEN;
    }

    const fetchOptions: RequestInit = { method, headers };

    if (["POST", "PUT"].includes(method)) {
      const body = await request.text();
      if (body.length > MAX_BODY_SIZE) {
        return NextResponse.json({ error: "Request body too large" }, { status: 413 });
      }
      fetchOptions.body = body;
    }

    // SSE streaming: detect by Accept header or URL suffix
    if (handleStreaming) {
      const accept = request.headers.get("accept") || "";
      const url = new URL(request.url);
      if (accept.includes("text/event-stream") || url.pathname.endsWith("/stream")) {
        const streamRes = await withCircuitBreaker("backend", () =>
          fetch(targetUrl, fetchOptions),
        );
        return new Response(streamRes.body, {
          status: streamRes.status,
          headers: {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
          },
        });
      }
    }

    const response = await withCircuitBreaker("backend", () =>
      fetchWithRetry(targetUrl, fetchOptions),
    );

    const respHeaders: Record<string, string> = {};
    if (forwardSetCookie) {
      response.headers.forEach((value, key) => {
        if (key.toLowerCase() === "set-cookie") {
          respHeaders[key] = value;
        }
      });
    }

    const text = await response.text();
    try {
      const data = JSON.parse(text);
      return NextResponse.json(data, {
        status: response.status,
        headers: Object.keys(respHeaders).length > 0 ? respHeaders : undefined,
      });
    } catch {
      return new NextResponse(text, {
        status: response.status,
        headers: {
          "content-type": response.headers.get("content-type") || "text/plain",
          ...respHeaders,
        },
      });
    }
  } catch (error) {
    if (error instanceof CircuitOpenError) {
      return NextResponse.json(
        { error: "Service temporarily unavailable" },
        {
          status: 503,
          headers: { "Retry-After": "30" },
        },
      );
    }
    logger.error("Proxy error:", error);
    return NextResponse.json({ error: "Backend service unavailable" }, { status: 502 });
  }
}
