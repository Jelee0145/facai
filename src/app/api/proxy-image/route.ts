import { NextRequest, NextResponse } from "next/server";
import { promises as dns } from "dns";

const MAX_SIZE = 10 * 1024 * 1024;
const FETCH_TIMEOUT = 30_000;

const PRIVATE_RANGES = [
  /^127\./, /^10\./, /^0\./,
  /^172\.(1[6-9]|2\d|3[01])\./, /^192\.168\./,
  /^169\.254\./, /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./,
  /^::1$/, /^fc00:/, /^fe80:/,
  /^::ffff:127\./, /^::ffff:10\./, /^::ffff:0\./,
  /^::ffff:172\.(1[6-9]|2\d|3[01])\./, /^::ffff:192\.168\./,
  /^::ffff:169\.254\./,
];

const BLOCKED_HOSTNAMES = ["localhost", "127.0.0.1", "0.0.0.0", "[::1]", "metadata.google.internal"];

function isPrivateIP(ip: string): boolean {
  const lower = ip.toLowerCase();
  if (BLOCKED_HOSTNAMES.includes(lower)) return true;
  return PRIVATE_RANGES.some((r) => r.test(lower));
}

function normalizeIP(ip: string): string {
  const m = ip.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
  return m ? m[1] : ip;
}

async function resolveAndCheck(url: URL): Promise<string | null> {
  try {
    const addrs = await dns.resolve4(url.hostname);
    for (const addr of addrs) {
      if (isPrivateIP(addr)) {
        return `Private IP resolved: ${addr}`;
      }
    }
  } catch {
    // DNS resolution failure is not fatal for initial check
  }
  try {
    const addrs6 = await dns.resolve6(url.hostname);
    for (const addr of addrs6) {
      if (isPrivateIP(normalizeIP(addr))) {
        return `Private IPv6 resolved: ${addr}`;
      }
    }
  } catch {
    // IPv6 resolution failure is not fatal
  }
  return null;
}

export async function GET(request: NextRequest) {
  const rawUrl = request.nextUrl.searchParams.get("url");
  if (!rawUrl) {
    return NextResponse.json({ error: "Missing url parameter" }, { status: 400 });
  }

  let targetUrl: URL;
  try {
    targetUrl = new URL(decodeURIComponent(rawUrl));
  } catch {
    return NextResponse.json({ error: "Invalid url" }, { status: 400 });
  }

  if (targetUrl.protocol !== "https:") {
    return NextResponse.json({ error: "Only HTTPS allowed" }, { status: 403 });
  }

  if (isPrivateIP(targetUrl.hostname)) {
    return NextResponse.json({ error: "Private target not allowed" }, { status: 403 });
  }

  const dnsCheck = await resolveAndCheck(targetUrl);
  if (dnsCheck) {
    return NextResponse.json({ error: dnsCheck }, { status: 403 });
  }

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT);

    const resp = await fetch(targetUrl.toString(), { signal: controller.signal });
    clearTimeout(timer);

    if (!resp.ok) {
      return NextResponse.json({ error: "Upstream fetch failed" }, { status: 502 });
    }

    const contentType = resp.headers.get("content-type") || "image/png";
    const contentLength = resp.headers.get("content-length");
    if (contentLength && parseInt(contentLength) > MAX_SIZE) {
      return NextResponse.json({ error: "Image too large" }, { status: 413 });
    }

    const buffer = await resp.arrayBuffer();
    if (buffer.byteLength > MAX_SIZE) {
      return NextResponse.json({ error: "Image too large" }, { status: 413 });
    }

    return new NextResponse(buffer, {
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "public, max-age=31536000",
        "Access-Control-Allow-Origin": "*",
      },
    });
  } catch {
    return NextResponse.json({ error: "Failed to fetch image" }, { status: 502 });
  }
}
