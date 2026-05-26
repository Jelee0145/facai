import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/proxy";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "POST", await params, {
    targetPrefix: "/api/generate",
    handleStreaming: true,
  });
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "GET", await params, {
    targetPrefix: "/api/generate",
    handleStreaming: true,
  });
}
