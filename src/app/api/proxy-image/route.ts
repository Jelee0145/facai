import { NextRequest, NextResponse } from "next/server";
import { promises as dns } from "dns";

const BACKEND_URL = (process.env.BACKEND_URL || "http://localhost:8001").trim();
const ALLOWED_ORIGINS = new Set([
  "http://localhost:4524",
  BACKEND_URL.endsWith("/") ? BACKEND_URL.slice(0, -1) : BACKEND_URL,
]);

function getAllowedOrigin(request: NextRequest): string | null {
  const origin = request.headers.get("origin");
  if (!origin) return null;
  if (ALLOWED_ORIGINS.has(origin)) return origin;
  return null;
}

const MAX_SIZE = 10 * 1024 * 1024;
const FETCH_TIMEOUT = 30_000;
const MAGIC_HEADER_BYTES = 16;

const PRIVATE_RANGES = [
  /^127\./, /^10\./, /^0\./,
  /^172\.(1[6-9]|2\d|3[01])\./, /^192\.168\./,
  /^169\.254\./, /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./,
  /^::1$/, /^fc00:/, /^fe80:/,
  /^::ffff:127\./, /^::ffff:10\./, /^::ffff:0\./,
  /^::ffff:172\.(1[6-9]|2\d|3[01])\./, /^::ffff:192\.168\./,
  /^::ffff:169\.254\./,
];

const BLOCKED_HOSTNAMES = new Set([
  "localhost", "127.0.0.1", "0.0.0.0", "[::1]",
  "metadata.google.internal", "metadata.google",
  "metadata.azure.internal", "metadata",
  "instance-data", "169.254.169.254", "[::ffff:169.254.169.254]",
]);

// SVG excluded — script/link injection risk in proxied content
const ALLOWED_IMAGE_MIME = new Set([
  "image/jpeg", "image/png", "image/webp", "image/gif", "image/avif",
]);

// ---- Pure helper functions (testable) ----

export function normalizeHostname(hostname: string): string {
  return hostname.toLowerCase().replace(/\.$/, "");
}

export function isBlockedHostname(hostname: string): boolean {
  const normalized = normalizeHostname(hostname);
  if (BLOCKED_HOSTNAMES.has(normalized)) return true;
  if (normalized === "::ffff:a9fe.a9fe" || normalized === "::ffff:169.254.169.254") return true;
  return false;
}

export function isBlockedIp(ip: string): boolean {
  const lower = normalizeIP(ip).toLowerCase();
  if (BLOCKED_HOSTNAMES.has(lower)) return true;
  return PRIVATE_RANGES.some((r) => r.test(lower));
}

function normalizeIP(ip: string): string {
  const m = ip.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
  return m ? m[1] : ip;
}

/**
 * Validate Content-Type header. Fail-closed: missing or non-image = rejected.
 * Returns normalized MIME or throws.
 */
export function validateImageContentType(raw: string | null): string {
  if (!raw) {
    throw new Error("Content-Type header missing");
  }
  const mime = raw.split(";")[0].trim().toLowerCase();
  if (!mime) {
    throw new Error("Content-Type header empty");
  }
  if (!ALLOWED_IMAGE_MIME.has(mime)) {
    throw new Error(`Unsupported content type: ${mime}`);
  }
  return mime;
}

/**
 * Detect image format from magic bytes.
 * Returns MIME string or null if unrecognised.
 */
export function detectImageMagic(bytes: Uint8Array): string | null {
  if (bytes.length < 4) return null;
  // JPEG: FF D8 FF
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image/jpeg";
  // PNG: 89 50 4E 47
  if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return "image/png";
  // GIF: GIF87a or GIF89a
  if (bytes[0] === 0x47 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x38) return "image/gif";
  // WebP: RIFF....WEBP (bytes 0-3 = RIFF, bytes 8-11 = WEBP)
  if (bytes.length >= 12 &&
      bytes[0] === 0x52 && bytes[1] === 0x49 && bytes[2] === 0x46 && bytes[3] === 0x46 &&
      bytes[8] === 0x57 && bytes[9] === 0x45 && bytes[10] === 0x42 && bytes[11] === 0x50) return "image/webp";
  // AVIF/HEIF: ftyp box at offset 4
  if (bytes.length >= 12 && bytes[4] === 0x66 && bytes[5] === 0x74 && bytes[6] === 0x79 && bytes[7] === 0x70) {
    const brand = String.fromCharCode(bytes[8], bytes[9], bytes[10], bytes[11]);
    if (brand === "avif" || brand === "avis" || brand === "heic" || brand === "mif1") return "image/avif";
  }
  return null;
}

// ---- DNS helpers ----

async function resolveAndCheck(hostname: string): Promise<string | null> {
  let v4Addrs: string[] = [];
  let v6Addrs: string[] = [];
  let v4Ok = false;
  let v6Ok = false;

  try {
    v4Addrs = await dns.resolve4(hostname);
    v4Ok = true;
  } catch { /* v4 failed */ }
  try {
    v6Addrs = await dns.resolve6(hostname);
    v6Ok = true;
  } catch { /* v6 failed */ }

  // Fail-closed: reject if both DNS lookups failed AND yielded no addresses
  if (!v4Ok && !v6Ok && v4Addrs.length === 0 && v6Addrs.length === 0) {
    return "DNS resolution failed";
  }

  // Require at least one resolved address
  if (v4Addrs.length === 0 && v6Addrs.length === 0) {
    return "DNS resolved no addresses";
  }

  for (const addr of v4Addrs) {
    if (isBlockedIp(addr)) return `Private IP resolved: ${addr}`;
  }
  for (const addr of v6Addrs) {
    if (isBlockedIp(normalizeIP(addr))) return `Private IPv6 resolved: ${addr}`;
  }
  return null;
}

// ---- Streaming read with size cap ----

async function readStreamWithCap(
  body: ReadableStream<Uint8Array>,
  maxSize: number,
): Promise<{ header: Uint8Array; fullBuffer: Uint8Array; exceeded: boolean }> {
  const reader = body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  let headerBytes: Uint8Array | null = null;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;

      totalBytes += value.length;
      if (totalBytes > maxSize) {
        // Exceeded — cancel and return
        await reader.cancel();
        const partial = new Uint8Array(MAGIC_HEADER_BYTES);
        let copied = 0;
        for (const chunk of chunks) {
          const take = Math.min(chunk.length, MAGIC_HEADER_BYTES - copied);
          partial.set(chunk.subarray(0, take), copied);
          copied += take;
          if (copied >= MAGIC_HEADER_BYTES) break;
        }
        return { header: partial, fullBuffer: new Uint8Array(0), exceeded: true };
      }

      chunks.push(value);
      if (!headerBytes && totalBytes >= MAGIC_HEADER_BYTES) {
        // Collect header from accumulated chunks
        headerBytes = new Uint8Array(MAGIC_HEADER_BYTES);
        let offset = 0;
        for (const chunk of chunks) {
          const take = Math.min(chunk.length, MAGIC_HEADER_BYTES - offset);
          headerBytes.set(chunk.subarray(0, take), offset);
          offset += take;
          if (offset >= MAGIC_HEADER_BYTES) break;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  // Concatenate all chunks
  const fullBuffer = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    fullBuffer.set(chunk, offset);
    offset += chunk.length;
  }

  const header = headerBytes ?? fullBuffer.subarray(0, Math.min(fullBuffer.length, MAGIC_HEADER_BYTES));
  return { header, fullBuffer, exceeded: false };
}

// ---- Route handler ----

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

  if (isBlockedIp(targetUrl.hostname) || isBlockedHostname(targetUrl.hostname)) {
    return NextResponse.json({ error: "Private target not allowed" }, { status: 403 });
  }

  const dnsCheck = await resolveAndCheck(targetUrl.hostname);
  if (dnsCheck) {
    return NextResponse.json({ error: "Request blocked" }, { status: 403 });
  }

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT);

    const resp = await fetch(targetUrl.toString(), {
      signal: controller.signal,
      redirect: "manual",
    });
    clearTimeout(timer);

    // 3xx: reject (redirect: "manual" means we get 3xx as-is)
    if (resp.status >= 300 && resp.status < 400) {
      return NextResponse.json({ error: "Redirects are not allowed" }, { status: 403 });
    }

    if (!resp.ok) {
      return NextResponse.json({ error: "Upstream fetch failed" }, { status: 502 });
    }

    // DNS TOCTOU mitigation: verify final URL hostname matches original
    // (redirect: "manual" prevents this, but belt-and-suspenders)
    if (resp.url) {
      try {
        const finalUrl = new URL(resp.url);
        if (normalizeHostname(finalUrl.hostname) !== normalizeHostname(targetUrl.hostname)) {
          return NextResponse.json({ error: "Hostname mismatch after fetch" }, { status: 403 });
        }
      } catch { /* resp.url may be empty/opaque — acceptable */ }
    }

    // Content-Type: fail-closed on missing or non-image
    let contentType: string;
    try {
      contentType = validateImageContentType(resp.headers.get("content-type"));
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Invalid content type";
      return NextResponse.json({ error: msg }, { status: 415 });
    }

    // Pre-check Content-Length if present
    const contentLength = resp.headers.get("content-length");
    if (contentLength && parseInt(contentLength) > MAX_SIZE) {
      return NextResponse.json({ error: "Image too large" }, { status: 413 });
    }

    // Stream-read body with size cap
    if (!resp.body) {
      return NextResponse.json({ error: "Empty response body" }, { status: 502 });
    }

    const { header, fullBuffer, exceeded } = await readStreamWithCap(resp.body, MAX_SIZE);
    if (exceeded) {
      return NextResponse.json({ error: "Image too large" }, { status: 413 });
    }

    // Magic bytes validation
    const detectedMime = detectImageMagic(header);
    if (!detectedMime) {
      return NextResponse.json({ error: "Unrecognised image format" }, { status: 415 });
    }
    if (detectedMime !== contentType) {
      return NextResponse.json(
        { error: "Content-Type does not match actual image format" },
        { status: 415 },
      );
    }

    const corsOrigin = getAllowedOrigin(request);
    const resHeaders: Record<string, string> = {
      "Content-Type": contentType,
      "Cache-Control": "public, max-age=31536000",
    };
    if (corsOrigin) {
      resHeaders["Access-Control-Allow-Origin"] = corsOrigin;
    }

    return new NextResponse(fullBuffer.slice().buffer as ArrayBuffer, { headers: resHeaders });
  } catch {
    return NextResponse.json({ error: "Failed to fetch image" }, { status: 502 });
  }
}
