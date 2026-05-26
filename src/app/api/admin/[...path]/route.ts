import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/proxy";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "GET", await params, {
    targetPrefix: "/admin",
    forwardCookies: true,
    forwardSetCookie: true,
  });
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "POST", await params, {
    targetPrefix: "/admin",
    forwardCookies: true,
    forwardSetCookie: true,
  });
}

export async function PUT(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "PUT", await params, {
    targetPrefix: "/admin",
    forwardCookies: true,
    forwardSetCookie: true,
  });
}

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxyToBackend(request, "DELETE", await params, {
    targetPrefix: "/admin",
    forwardCookies: true,
    forwardSetCookie: true,
  });
}
