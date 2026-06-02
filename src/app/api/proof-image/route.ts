import { NextRequest } from "next/server";

const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8001").trim().replace(/\s+/g, "").replace(/\/+$/, "");

export async function GET(request: NextRequest) {
  const path = request.nextUrl.searchParams.get("path");
  if (!path || !path.startsWith("/uploads/proofs/")) {
    return new Response("Bad Request", { status: 400 });
  }
  try {
    const response = await fetch(`${BACKEND_URL}${path}`);
    if (!response.ok) {
      return new Response("Not Found", { status: 404 });
    }
    const contentType = response.headers.get("content-type") || "image/png";
    const body = await response.arrayBuffer();
    return new Response(body, {
      status: 200,
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "public, max-age=86400",
      },
    });
  } catch {
    return new Response("Backend Unavailable", { status: 502 });
  }
}
