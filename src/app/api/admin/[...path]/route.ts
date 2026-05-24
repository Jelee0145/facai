import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8001";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "GET", await params);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "POST", await params);
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "PUT", await params);
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "DELETE", await params);
}

const MAX_BODY_SIZE = 10 * 1024 * 1024; // 10MB

async function proxyToBackend(
  request: NextRequest,
  method: string,
  params: { path: string[] }
) {
  try {
    const subPath = params.path.join("/");
    const url = new URL(request.url);
    const targetUrl = `${BACKEND_URL}/admin/${subPath}${url.search}`;

    const bodyText = ["POST", "PUT"].includes(method) ? await request.text() : undefined;
    if (bodyText && bodyText.length > MAX_BODY_SIZE) {
      return NextResponse.json(
        { error: "Request body too large" },
        { status: 413 }
      );
    }

    const reqHeaders: Record<string, string> = {};
    request.headers.forEach((value, key) => {
      if (key.toLowerCase() === "cookie") {
        reqHeaders[key] = value;
      }
    });

    const fetchOptions: RequestInit = {
      method,
      headers: {
        "Content-Type": "application/json",
        ...reqHeaders,
      },
      body: bodyText,
    };

    const response = await fetch(targetUrl, fetchOptions);

    const respHeaders: Record<string, string> = {};
    response.headers.forEach((value, key) => {
      if (key.toLowerCase() === "set-cookie") {
        respHeaders[key] = value;
      }
    });

    const text = await response.text();
    try {
      const data = JSON.parse(text);
      return NextResponse.json(data, { status: response.status, headers: respHeaders });
    } catch {
      return new NextResponse(text, {
        status: response.status,
        headers: { "content-type": response.headers.get("content-type") || "text/plain", ...respHeaders },
      });
    }
  } catch (error) {
    console.error("Admin proxy error:", error);
    return NextResponse.json(
      { error: "Backend service unavailable" },
      { status: 502 }
    );
  }
}
