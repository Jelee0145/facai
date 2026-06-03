import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/proxy";

export async function GET(request: NextRequest) {
  return proxyToBackend(request, "GET", undefined, {
    targetPrefix: "/api/custom-types",
    forwardCookies: true,
  });
}

export async function POST(request: NextRequest) {
  return proxyToBackend(request, "POST", undefined, {
    targetPrefix: "/api/custom-types",
    forwardCookies: true,
  });
}
