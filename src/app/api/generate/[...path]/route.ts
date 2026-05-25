/**
 * 代理 /api/generate/* (async, status/taskId 等) → FastAPI
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8001").trim();
const API_AUTH_TOKEN = process.env.API_AUTH_TOKEN || "";
const MAX_BODY_SIZE = 10 * 1024 * 1024; // 10MB

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "POST", await params);
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "GET", await params);
}

async function proxyToBackend(
  request: NextRequest,
  method: string,
  params: { path: string[] }
) {
  try {
    const subPath = params.path.join("/");
    const url = new URL(request.url);
    const targetUrl = `${BACKEND_URL}/api/generate/${subPath}${url.search}`;

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

    const fetchOptions: RequestInit = { method, headers };
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
    console.error("Catch-all proxy error:", error);
    return NextResponse.json(
      { error: "Backend service unavailable" },
      { status: 502 }
    );
  }
}
