/**
 * API 代理 — 所有 /api/generate/* 请求转发到 FastAPI 后端
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8001").trim();
const API_AUTH_TOKEN = process.env.API_AUTH_TOKEN || "";
const MAX_BODY_SIZE = 10 * 1024 * 1024; // 10MB

export async function POST(request: NextRequest) {
  return proxyRequest(request, "POST");
}

export async function GET(request: NextRequest) {
  return proxyRequest(request, "GET");
}

async function proxyRequest(request: NextRequest, method: string) {
  try {
    const url = new URL(request.url);
    // 将 /api/generate/... 转发到 FastAPI
    const targetUrl = `${BACKEND_URL}${url.pathname}${url.search}`;

    const headers: Record<string, string> = {};
    request.headers.forEach((value, key) => {
      const k = key.toLowerCase();
      if (k !== "host" && k !== "content-length" && k !== "transfer-encoding" && k !== "expect") {
        headers[key] = value;
      }
    });
    if (API_AUTH_TOKEN) {
      headers["X-API-Auth"] = API_AUTH_TOKEN;
    }

    const fetchOptions: RequestInit = {
      method,
      headers,
    };

    if (method === "POST") {
      const body = await request.text();
      if (body.length > MAX_BODY_SIZE) {
        return NextResponse.json(
          { error: "Request body too large" },
          { status: 413 }
        );
      }
      fetchOptions.body = body;
    }

    const response = await fetch(targetUrl, fetchOptions);

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error("API proxy error:", error);
    return NextResponse.json(
      { error: "Backend service unavailable" },
      { status: 502 }
    );
  }
}
